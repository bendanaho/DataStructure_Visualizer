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

from stack.st_model import StackModel
from stack.st_view import StackView


class StackController(QWidget):
    """Controller for the stack visualization."""

    def __init__(self, global_ctrl):
        super().__init__()
        self.model = StackModel()
        self.view = StackView(global_ctrl)
        self.panel_index = -1
        self.panel = self._build_panel()
        self.view.interactionLocked.connect(self._toggle_controls)
        self.view.clearAllRequested.connect(self._on_clear_all_requested)

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