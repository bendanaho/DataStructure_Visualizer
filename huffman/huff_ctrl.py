import re
from typing import List

from PyQt5.QtWidgets import (
    QFormLayout,
    QGroupBox,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
    QMessageBox,
)

from core.global_ctrl import GlobalController
from huffman.huff_model import HuffmanModel
from huffman.huff_view import HuffmanView


class HuffmanController(QWidget):
    """
    单一操作：“构建哈夫曼树”，输入一组正数，按顺序播放排序 + 构建动画。
    """

    def __init__(self, global_ctrl: GlobalController):
        super().__init__()
        self.model = HuffmanModel()
        self.view = HuffmanView(global_ctrl)
        self._panel_locked = False

        self.input_edit = QLineEdit()
        self.input_edit.setPlaceholderText("例如：5, 9, 12, 13, 16, 45")
        self.input_edit.returnPressed.connect(self._on_build)

        self.build_btn = QPushButton("构建哈夫曼树")
        self.build_btn.clicked.connect(self._on_build)

        self.panel = self._create_panel()
        self.view.interactionLocked.connect(self._handle_lock)

    def _create_panel(self):
        group = QGroupBox("Huffman Builder")
        group.setStyleSheet("QGroupBox { color: white; }")
        form = QFormLayout()
        form.setContentsMargins(12, 10, 12, 12)
        form.setSpacing(8)
        form.addRow("权重列表:", self.input_edit)
        form.addRow(self.build_btn)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(group)
        layout.addStretch(1)
        group.setLayout(form)
        return container

    # ---------- 生命周期 ----------

    def build_panel(self):
        return self.panel

    def on_activate(self, graphics_view):
        self.view.bind_canvas(graphics_view)
        graphics_view.setScene(self.view.scene)

    def on_deactivate(self):
        pass

    # ---------- 逻辑 ----------

    def _on_build(self):
        values = self._parse_values(self.input_edit.text())
        if values is None:
            return
        process = self.model.build_process(values)
        if not process["sorting"] and not process["building"]:
            QMessageBox.information(self, "提示", "请输入至少一个正数。")
            return
        self.view.play_process(process)

    def _parse_values(self, text: str):
        text = text.strip()
        if not text:
            QMessageBox.warning(self, "提示", "请输入至少一个权重。")
            return None
        normalized = text.replace("，", ",")
        tokens = [t for t in re.split(r"[,\s]+", normalized) if t]
        values: List[float] = []
        for token in tokens:
            try:
                value = float(token)
            except ValueError:
                QMessageBox.warning(self, "非法输入", f"“{token}” 不是有效的数值。")
                return None
            if value <= 0:
                QMessageBox.warning(self, "非法输入", "所有权重必须是正数。")
                return None
            values.append(value)
        return values

    def _handle_lock(self, locked: bool):
        self._panel_locked = locked
        self.build_btn.setDisabled(locked)
        self.input_edit.setDisabled(locked)