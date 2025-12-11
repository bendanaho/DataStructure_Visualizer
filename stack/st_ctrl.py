from PyQt5.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

import json
from pathlib import Path
from PyQt5.QtWidgets import QFileDialog

from stack.st_model import StackModel
from stack.st_view import StackView
from stack.st_view import StackViewWithPersistence


class StackController(QWidget):
    """Controller for the stack visualization."""

    def __init__(self, global_ctrl):
        super().__init__()
        self.model = StackModel()
        self.view = StackViewWithPersistence(global_ctrl)
        self.panel_index = -1
        self.panel = self._build_panel()
        self.view.interactionLocked.connect(self._toggle_controls)
        self.view.clearAllRequested.connect(self._on_clear_all_requested)
        self.view.saveRequested.connect(self._save_to_file)
        self.view.loadRequested.connect(self._load_from_file)

    def _save_to_file(self):
        snapshot = self.model.snapshot()
        if not snapshot:
            QMessageBox.information(self, "Stack", "当前栈为空，无需保存。")
            return

        base_dir = Path(__file__).resolve().parents[1] / "save_file" / "stack"
        base_dir.mkdir(parents=True, exist_ok=True)
        suggested = str(base_dir / "stack.json")

        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Stack",
            suggested,
            "Stack (*.json);;All Files (*)",
        )
        if not path:
            return
        if not path.lower().endswith(".json"):
            path += ".json"

        payload = {
            "schema": "pyqt_ds_visualizer",
            "version": 1,
            "structure": "stack",
            "nodes": snapshot,
            "popped_values": self.view.export_popped_values(),
        }

        try:
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, ensure_ascii=False, indent=2)
        except OSError as exc:
            QMessageBox.critical(self, "Save Failed", f"无法写入文件：\n{exc}")
            return

        QMessageBox.information(self, "Stack", f"已保存到：\n{path}")

    def _load_from_file(self):
        base_dir = Path(__file__).resolve().parents[1] / "save_file" / "stack"
        base_dir.mkdir(parents=True, exist_ok=True)

        path, _ = QFileDialog.getOpenFileName(
            self,
            "Open Stack",
            str(base_dir),
            "Stack (*.json);;All Files (*)",
        )
        if not path:
            return

        try:
            with open(path, "r", encoding="utf-8") as fh:
                payload = json.load(fh)
        except (OSError, json.JSONDecodeError) as exc:
            QMessageBox.critical(self, "Open Failed", f"无法读取文件：\n{exc}")
            return

        if (
                payload.get("schema") != "pyqt_ds_visualizer"
                or payload.get("structure") != "stack"
        ):
            QMessageBox.critical(self, "Open Failed", "文件格式不受支持。")
            return

        nodes = payload.get("nodes", [])
        popped_values = payload.get("popped_values", [])

        self.model.load_snapshot(nodes)
        snapshot = self.model.snapshot()

        self.view.reset()
        if snapshot:
            self.view.relayout_stack(snapshot)
        self.view.load_popped_values(popped_values)

        QMessageBox.information(self, "Stack", "文件加载完成。")

    def _build_panel(self):
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        push_group = QGroupBox("Push")
        push_group.setStyleSheet(
            """
            QGroupBox {
                border: 1px solid #d5d5d5;
                border-radius: 6px;
                margin-top: 12px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 6px;
                color: #ffffff;
            }
            """
        )
        push_group_layout = QVBoxLayout(push_group)
        push_group_layout.setContentsMargins(12, 20, 12, 12)
        push_group_layout.setSpacing(8)

        self.push_input = QLineEdit()
        self.push_input.setPlaceholderText("Value")
        push_group_layout.addWidget(self.push_input)

        self.push_btn = QPushButton("Push")
        self.push_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.push_btn.clicked.connect(self._on_push)
        push_group_layout.addWidget(self.push_btn)

        layout.addWidget(push_group)

        pop_group = QGroupBox("Pop")
        pop_group.setStyleSheet(
            """
            QGroupBox {
                border: 1px solid #d5d5d5;
                border-radius: 6px;
                margin-top: 4px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 6px;
                color: #ffffff;
            }
            """
        )
        pop_group_layout = QVBoxLayout(pop_group)
        pop_group_layout.setContentsMargins(12, 24, 12, 12)
        pop_group_layout.setSpacing(8)

        self.pop_btn = QPushButton("Pop")
        self.pop_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.pop_btn.clicked.connect(self._on_pop)
        pop_group_layout.addWidget(self.pop_btn)

        layout.addWidget(pop_group)

        layout.addStretch(1)
        return container

    def build_panel(self):
        return self.panel

    def on_activate(self, graphics_view):
        self.view.bind_canvas(graphics_view)
        graphics_view.setScene(self.view.scene)
        self.view.on_canvas_ready()

    def on_deactivate(self):
        pass

    def _on_push(self):
        value_text = self.push_input.text().strip()
        if not value_text:
            value_text = "∅"
        value = self._coerce_value(value_text)
        info = self.model.push(value)
        self.view.animate_push(self.model.snapshot(), info)
        self.push_input.clear()

    def _on_pop(self):
        if len(self.model) == 0:
            QMessageBox.information(self, "Stack", "Stack is empty.")
            return
        popped = self.model.pop()
        self.view.animate_pop(self.model.snapshot(), popped)

    def _toggle_controls(self, locked):
        self.push_btn.setDisabled(locked)
        self.pop_btn.setDisabled(locked)
        self.push_input.setDisabled(locked)

    @staticmethod
    def _coerce_value(value):
        try:
            return int(value)
        except ValueError:
            try:
                return float(value)
            except ValueError:
                return value

    def _on_clear_all_requested(self):
        self.model = StackModel()
        self.view.reset()