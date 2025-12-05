import re
from typing import Optional

from PyQt5.QtWidgets import (
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QInputDialog,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
    QMessageBox
)

from core.global_ctrl import GlobalController
from bst.bst_model import BSTModel
    # (路径以你创建的模块名为准)
from bst.bst_view import BSTView


class BSTController(QWidget):
    """
    构建 BST 操作面板，并负责模型与视图之间的桥接。
    """

    def __init__(self, global_ctrl: GlobalController):
        super().__init__()
        self.model = BSTModel()
        self.view = BSTView(global_ctrl)
        self._panel_locked = False

        self._build_inputs()
        self.panel = self._create_panel()

        self.view.interactionLocked.connect(self._on_lock_state)
        self.view.deleteRequested.connect(self._handle_delete_from_view)
        self.view.findRequested.connect(self._handle_find_from_view)

        self._refresh_inputs()

    # ---------- UI 构建 ----------
    def _build_inputs(self):
        self.insert_value_edit = QLineEdit()
        self.insert_value_edit.setPlaceholderText("Value")
        self.insert_value_edit.returnPressed.connect(self._on_insert)

        self.delete_value_edit = QLineEdit()
        self.delete_value_edit.setPlaceholderText("Value")
        self.delete_value_edit.returnPressed.connect(self._on_delete)

        self.find_value_edit = QLineEdit()
        self.find_value_edit.setPlaceholderText("Value")
        self.find_value_edit.returnPressed.connect(self._on_find)

    def _create_panel(self):
        container = QWidget()
        layout = QGridLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setHorizontalSpacing(12)
        layout.setVerticalSpacing(12)
        layout.setColumnStretch(0, 1)
        layout.setColumnStretch(1, 1)

        # Create
        create_btn = QPushButton("Create From List")
        create_btn.clicked.connect(self._on_create)
        layout.addWidget(self._single_button_group("Create", create_btn), 0, 0)

        # Insert
        insert_group = QGroupBox("Insert")
        insert_group.setStyleSheet("QGroupBox { color: white; }")
        insert_layout = QFormLayout()
        insert_layout.setContentsMargins(12, 8, 12, 12)
        insert_layout.setSpacing(6)
        insert_layout.addRow("Value:", self.insert_value_edit)
        insert_btn = QPushButton("Insert")
        insert_btn.clicked.connect(self._on_insert)
        insert_layout.addRow(insert_btn)
        insert_group.setLayout(insert_layout)
        layout.addWidget(insert_group, 1, 0)

        # Delete
        delete_group = QGroupBox("Delete")
        delete_group.setStyleSheet("QGroupBox { color: white; }")
        delete_layout = QFormLayout()
        delete_layout.setContentsMargins(12, 8, 12, 12)
        delete_layout.setSpacing(6)
        delete_layout.addRow("Value:", self.delete_value_edit)
        delete_btn = QPushButton("Delete")
        delete_btn.clicked.connect(self._on_delete)
        delete_layout.addRow(delete_btn)
        delete_group.setLayout(delete_layout)
        layout.addWidget(delete_group, 2, 0)

        # Find
        find_group = QGroupBox("Find")
        find_group.setStyleSheet("QGroupBox { color: white; }")
        find_layout = QFormLayout()
        find_layout.setContentsMargins(12, 8, 12, 12)
        find_layout.setSpacing(6)
        find_layout.addRow("Value:", self.find_value_edit)
        find_btn = QPushButton("Find")
        find_btn.clicked.connect(self._on_find)
        find_layout.addRow(find_btn)
        find_group.setLayout(find_layout)
        layout.addWidget(find_group, 0, 1, 2, 1)

        layout.setRowStretch(3, 1)

        self.create_btn = create_btn
        self.insert_btn = insert_btn
        self.delete_btn = delete_btn
        self.find_btn = find_btn

        return container

    @staticmethod
    def _single_button_group(title, button):
        group = QGroupBox(title)
        group.setStyleSheet("QGroupBox { color: white; }")
        vlayout = QVBoxLayout(group)
        vlayout.setContentsMargins(12, 10, 12, 12)
        vlayout.setSpacing(6)
        vlayout.addWidget(button)
        return group

    def build_panel(self):
        return self.panel

    # ---------- 生命周期 ----------

    def on_activate(self, graphics_view):
        self.view.bind_canvas(graphics_view)
        graphics_view.setScene(self.view.scene)

    def on_deactivate(self):
        pass

    # ---------- 操作回调 ----------
    def _require_value(self, edit: QLineEdit, action: str) -> Optional[str]:
        raw = edit.text().strip()
        if not raw:
            QMessageBox.warning(self, "Missing Value", f"请先输入要{action}的值。")
            return None
        return raw

    def _on_create(self):
        text, ok = QInputDialog.getText(
            self,
            "Create BST",
            "Enter values (comma-separated):",
        )
        if not ok:
            return
        try:
            values = self._parse_sequence(text)
        except ValueError:
            QMessageBox.warning(self, "Invalid Value", "创建列表中每个元素都必须是数值。")
            return

        self.model.create_from_iterable(values)
        snapshot = self.model.snapshot()
        if snapshot["nodes"]:
            self.view.animate_build(snapshot)
        else:
            self.view.reset()
        self._refresh_inputs()

    def _on_insert(self):
        raw = self._require_value(self.insert_value_edit, "插入")
        if raw is None:
            return
        value = self._coerce_numeric_or_warn(raw, "插入")
        if value is None:
            return
        inserted_id, path = self.model.insert(value)
        snapshot = self.model.snapshot()
        self.view.animate_insert(snapshot, inserted_id, path)
        self._refresh_inputs()

    def _on_delete(self):
        if self.model.length == 0:
            return
        raw = self._require_value(self.delete_value_edit, "删除")
        if raw is None:
            return
        value = self._coerce_numeric_or_warn(raw, "删除")
        if value is None:
            return
        removed_id, path = self.model.delete(value)
        snapshot = self.model.snapshot()
        if removed_id is None:
            self.view.animate_find(snapshot, None, path)
        else:
            self.view.animate_delete(snapshot, removed_id, path)
        self._refresh_inputs()

    def _on_find(self):
        if self.model.length == 0:
            return
        raw = self._require_value(self.find_value_edit, "查找")
        if raw is None:
            return
        value = self._coerce_numeric_or_warn(raw, "查找")
        if value is None:
            return
        found_id, path = self.model.find(value)
        snapshot = self.model.snapshot()
        self.view.animate_find(snapshot, found_id, path)

    def _coerce_numeric_or_warn(self, raw: str, action: str):
        try:
            return self._coerce_value(raw)
        except ValueError:
            QMessageBox.warning(self, "Invalid Value", f"{action}的值必须是数值（整数或小数）。")
            return None

    def _handle_delete_from_view(self, node_id):
        value = self.model.value_of(node_id)
        if value is None:
            return
        self.delete_value_edit.setText(str(value))
        self._on_delete()

    def _handle_find_from_view(self, node_id):
        value = self.model.value_of(node_id)
        if value is None:
            return
        self.find_value_edit.setText(str(value))
        self._on_find()

    def _on_clear_all_requested(self):
        self.model.clear()
        self.view.reset()
        self._refresh_inputs()

    # ---------- 状态管理 ----------

    def _refresh_inputs(self):
        has_nodes = self.model.length > 0
        state = self._panel_locked
        self.create_btn.setDisabled(state)
        self.insert_btn.setDisabled(state)
        self.insert_value_edit.setDisabled(state)

        for widget in (
            self.delete_btn,
            self.delete_value_edit,
            self.find_btn,
            self.find_value_edit,
        ):
            widget.setDisabled(state or not has_nodes)

    def _on_lock_state(self, locked):
        self._panel_locked = locked
        self._refresh_inputs()

    # ---------- Helpers ----------

    @staticmethod
    def _parse_sequence(text: str):
        if not text:
            return []
        normalized = text.replace("，", ",")
        tokens = [
            part.strip()
            for part in re.split(r"[,\s]+", normalized)
            if part.strip()
        ]
        if not tokens:
            return []
        return [BSTController._coerce_value(tok) for tok in tokens]

    @staticmethod
    def _coerce_value(value):
        try:
            return int(value)
        except ValueError:
            pass
        try:
            return float(value)
        except ValueError:
            raise ValueError("value is not numeric")