import re

from PyQt5.QtWidgets import (
    QFormLayout,
    QGridLayout,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
    QInputDialog,
    QGroupBox,
)

from core.global_ctrl import GlobalController
from linklist.sl_model import LinkedListModel
from linklist.sl_view import LinkedListView


class LinkedListController(QWidget):
    """
    Controller builds the operation panel and wires UI events -> model -> view.
    """

    def __init__(self, global_ctrl: GlobalController):
        super().__init__()
        self.model = LinkedListModel()
        self.view = LinkedListView(global_ctrl)
        self.panel_index = -1
        self._panel_locked = False

        self._build_inputs()
        self.panel = self._create_panel()

        self.view.interactionLocked.connect(self._on_lock_state)
        self.view.deleteRequested.connect(self._handle_delete_from_node)
        self.view.editRequested.connect(self._handle_edit_from_node)
        self.view.clearAllRequested.connect(self._on_clear_all_requested)

        self._refresh_spins()

    # ---------- Panel UI ----------

    def _create_panel(self):
        container = QWidget()
        layout = QGridLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setHorizontalSpacing(12)
        layout.setVerticalSpacing(12)
        layout.setColumnStretch(0, 1)
        layout.setColumnStretch(1, 1)

        # Create From List
        create_btn = QPushButton("Create From List")
        create_btn.clicked.connect(self._on_create)
        create_group = self._single_button_group("Create", create_btn)
        layout.addWidget(create_group, 0, 0)

        # Append Tail
        append_btn = QPushButton("Append Tail")
        append_btn.clicked.connect(self._on_append_tail)
        append_group = self._single_button_group("Append Tail", append_btn)
        layout.addWidget(append_group, 1, 0)

        # Insert controls
        insert_group = QGroupBox("Insert At")
        insert_group.setStyleSheet("QGroupBox { color: white; }")
        insert_layout = QFormLayout()
        insert_layout.setContentsMargins(12, 8, 12, 12)
        insert_layout.setSpacing(6)
        insert_layout.addRow("Index:", self.insert_index_spin)
        insert_layout.addRow("Value:", self.insert_value_edit)
        insert_btn = QPushButton("Insert")
        insert_btn.clicked.connect(self._on_insert)
        insert_layout.addRow(insert_btn)
        insert_group.setLayout(insert_layout)
        layout.addWidget(insert_group, 2, 0)

        # Update controls（布局与 arr_ctrl 相同）
        update_group = QGroupBox("Update")
        update_group.setStyleSheet("QGroupBox { color: white; }")
        update_layout = QFormLayout()
        update_layout.setContentsMargins(12, 8, 12, 12)
        update_layout.setSpacing(6)
        update_layout.addRow("Index:", self.update_index_spin)
        update_layout.addRow("Value:", self.update_value_edit)
        update_btn = QPushButton("Update")
        update_btn.clicked.connect(self._on_update_value)
        update_layout.addRow(update_btn)
        update_group.setLayout(update_layout)
        layout.addWidget(update_group, 0, 1, 2, 1)

        # Delete controls
        delete_group = QGroupBox("Delete At")
        delete_group.setStyleSheet("QGroupBox { color: white; }")
        delete_layout = QFormLayout()
        delete_layout.setContentsMargins(12, 8, 12, 12)
        delete_layout.setSpacing(6)
        delete_layout.addRow("Index:", self.delete_index_spin)
        delete_btn = QPushButton("Delete")
        delete_btn.clicked.connect(self._on_delete)
        delete_layout.addRow(delete_btn)
        delete_group.setLayout(delete_layout)
        layout.addWidget(delete_group, 2, 1)

        layout.setRowStretch(3, 1)

        self.create_btn = create_btn
        self.append_btn = append_btn
        self.insert_btn = insert_btn
        self.update_btn = update_btn
        self.delete_btn = delete_btn
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

    def _build_inputs(self):
        self.insert_index_spin = QSpinBox()
        self.insert_index_spin.setRange(0, 0)

        self.insert_value_edit = QLineEdit()
        self.insert_value_edit.setPlaceholderText("Value")

        self.update_index_spin = QSpinBox()
        self.update_index_spin.setRange(0, 0)

        self.update_value_edit = QLineEdit()
        self.update_value_edit.setPlaceholderText("New value")

        self.delete_index_spin = QSpinBox()
        self.delete_index_spin.setRange(0, 0)

    def _refresh_spins(self):
        length = self.model.length
        self.insert_index_spin.setMaximum(length)
        if self.insert_index_spin.value() > length:
            self.insert_index_spin.setValue(length)

        max_index = max(0, length - 1)
        for spin in (self.delete_index_spin, self.update_index_spin):
            spin.setMaximum(max_index)
            if spin.value() > max_index:
                spin.setValue(max_index)

        has_nodes = length > 0
        if self._panel_locked:
            self.delete_index_spin.setDisabled(True)
            self.delete_btn.setDisabled(True)
            self.update_index_spin.setDisabled(True)
            self.update_value_edit.setDisabled(True)
            self.update_btn.setDisabled(True)
        else:
            self.delete_index_spin.setDisabled(not has_nodes)
            self.delete_btn.setDisabled(not has_nodes)
            self.update_index_spin.setDisabled(not has_nodes)
            self.update_value_edit.setDisabled(not has_nodes)
            self.update_btn.setDisabled(not has_nodes)

    # ---------- Controller lifecycle ----------

    def on_activate(self, graphics_view):
        self.view.bind_canvas(graphics_view)
        graphics_view.setScene(self.view.scene)

    def on_deactivate(self):
        pass

    def build_panel(self):
        return self.panel

    # ---------- UI handlers ----------

    def _on_create(self):
        text, ok = QInputDialog.getText(
            self, "Create Linked List", "Enter values (comma-separated):"
        )
        if not ok:
            return
        values = self._parse_sequence(text)
        self.model.create_from_iterable(values)
        snapshot = self.model.snapshot()
        if snapshot:
            self.view.animate_build(snapshot)
        else:
            self.view.reset()
        self._refresh_spins()

    def _on_append_tail(self):
        text, ok = QInputDialog.getText(
            self, "Append Tail", "New node value:"
        )
        if not ok:
            return
        value_text = text.strip() or "∅"
        value = self._coerce_value(value_text)
        index = self.model.length  # 尾部位置
        inserted_id = self.model.insert(index, value)
        snapshot = self.model.snapshot()
        self.view.animate_insert(snapshot, inserted_id, index)
        self._refresh_spins()

    def _on_insert(self):
        index = self.insert_index_spin.value()                  # 获取SpinBox的索引值
        value_text = self.insert_value_edit.text().strip()      # 获取输入框的值
        if not value_text:
            value_text = "∅"
        value = self._coerce_value(value_text)                  # 转换为int/float/str类型
        inserted_id = self.model.insert(index, value)           # ①调用模型层的插入方法
        snapshot = self.model.snapshot()
        self.view.animate_insert(snapshot, inserted_id, index)  # ②调用视图层的绘制动画
        self._refresh_spins()                                   # ③刷新UI控件状态

    def _on_update_value(self):
        if self.model.length == 0:
            return
        index = self.update_index_spin.value()
        value_text = self.update_value_edit.text().strip() or "∅"
        value = self._coerce_value(value_text)
        self.model.update_value(index, value)
        self.view.update_values(self.model.snapshot())
        self._refresh_spins()

    def _on_delete(self):
        if self.model.length == 0:
            return
        index = self.delete_index_spin.value()                      # 获取SpinBox的索引值
        removed = self.model.delete(index)                          # 1. 模型层删除
        snapshot = self.model.snapshot()
        self.view.animate_delete(snapshot, removed["id"], index)    # 2. 视图动画
        self._refresh_spins()                                       # 3. 刷新UI控件状态

    def _handle_delete_from_node(self, index):
        self.delete_index_spin.setValue(index)
        self._on_delete()

    def _handle_edit_from_node(self, index):
        node_snapshot = self.model.snapshot()[index]
        current = str(node_snapshot["value"])
        text, ok = QInputDialog.getText(
            self, "Edit Value", f"Node[{index}] value:", text=current
        )
        if not ok:
            return
        value = self._coerce_value(text.strip() or current)
        self.model.update_value(index, value)
        self.view.update_values(self.model.snapshot())
        self._refresh_spins()

    def _on_lock_state(self, locked):
        self._panel_locked = locked

        for widget in (
            self.create_btn,
            self.append_btn,
            self.insert_btn,
        ):
            widget.setDisabled(locked)

        self.insert_index_spin.setDisabled(locked)
        self.insert_value_edit.setDisabled(locked)

        if locked:
            self.delete_index_spin.setDisabled(True)
            self.delete_btn.setDisabled(True)
            self.update_index_spin.setDisabled(True)
            self.update_value_edit.setDisabled(True)
            self.update_btn.setDisabled(True)
        else:
            self._refresh_spins()

    def _on_clear_all_requested(self):
        self.model.clear()
        self.view.reset()
        self._refresh_spins()

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
        return [LinkedListController._coerce_value(part) for part in tokens]

    @staticmethod
    def _coerce_value(value):
        try:
            return int(value)
        except ValueError:
            try:
                return float(value)
            except ValueError:
                return value
