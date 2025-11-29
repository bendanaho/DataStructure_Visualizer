import re

from PyQt5.QtWidgets import (
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QInputDialog,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from core.global_ctrl import GlobalController
from arrayviz.arr_model import ArrayModel
from arrayviz.arr_view import ArrayView


class ArrayController(QWidget):
    """
    构建数组操作面板，并负责模型与视图之间的桥接。
    """

    def __init__(self, global_ctrl: GlobalController):
        super().__init__()
        self.model = ArrayModel()
        self.view = ArrayView(global_ctrl)
        self.panel_index = -1
        self._panel_locked = False

        self._build_inputs()
        self.panel = self._create_panel()

        self.view.interactionLocked.connect(self._on_lock_state)
        self.view.deleteRequested.connect(self._handle_delete_from_view)
        self.view.editRequested.connect(self._handle_edit_from_view)
        self.view.clearAllRequested.connect(self._on_clear_all_requested)

        self._refresh_spins()

    # ---------- Panel UI ----------

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
        create_group = self._single_button_group("Create", create_btn)
        layout.addWidget(create_group, 0, 0)

        # Append
        append_btn = QPushButton("Append")
        append_btn.clicked.connect(self._on_append)
        append_group = self._single_button_group("Append", append_btn)
        layout.addWidget(append_group, 1, 0)

        # Insert
        insert_btn = QPushButton("Insert")
        insert_btn.clicked.connect(self._on_insert)
        insert_group = QGroupBox("Insert")
        insert_group.setStyleSheet("QGroupBox { color: white; }")
        insert_layout = QFormLayout()
        insert_layout.setContentsMargins(12, 8, 12, 12)
        insert_layout.setSpacing(6)
        insert_layout.addRow("Index:", self.insert_index_spin)
        insert_layout.addRow("Value:", self.insert_value_edit)
        insert_layout.addRow(insert_btn)
        insert_group.setLayout(insert_layout)
        layout.addWidget(insert_group, 2, 0)

        # Update
        update_btn = QPushButton("Update")
        update_btn.clicked.connect(self._on_update_value)
        update_group = QGroupBox("Update")
        update_group.setStyleSheet("QGroupBox { color: white; }")
        update_layout = QFormLayout()
        update_layout.setContentsMargins(12, 8, 12, 12)
        update_layout.setSpacing(6)
        update_layout.addRow("Index:", self.update_index_spin)
        update_layout.addRow("Value:", self.update_value_edit)
        update_layout.addRow(update_btn)
        update_group.setLayout(update_layout)
        layout.addWidget(update_group, 0, 1, 2, 1)

        # Delete
        delete_btn = QPushButton("Delete")
        delete_btn.clicked.connect(self._on_delete)
        delete_group = QGroupBox("Delete")
        delete_group.setStyleSheet("QGroupBox { color: white; }")
        delete_layout = QFormLayout()
        delete_layout.setContentsMargins(12, 8, 12, 12)
        delete_layout.setSpacing(6)
        delete_layout.addRow("Index:", self.delete_index_spin)
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

    def build_panel(self):
        return self.panel

    # ---------- Controller lifecycle ----------

    def on_activate(self, graphics_view):
        self.view.bind_canvas(graphics_view)
        graphics_view.setScene(self.view.scene)

    def on_deactivate(self):
        pass

    # ---------- UI handlers ----------

    def _on_create(self):
        text, ok = QInputDialog.getText(
            self,
            "Create Array",
            "Enter values (comma-separated):",
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

    def _on_append(self):
        text, ok = QInputDialog.getText(
            self,
            "Append Value",
            "New element:",
        )
        if not ok:
            return
        value_text = text.strip() or "∅"
        value = self._coerce_value(value_text)
        index = self.model.length
        inserted_id = self.model.insert(index, value)
        snapshot = self.model.snapshot()
        self.view.animate_insert(snapshot, inserted_id, index)
        self._refresh_spins()

    def _on_insert(self):
        index = self.insert_index_spin.value()
        value_text = self.insert_value_edit.text().strip() or "∅"
        value = self._coerce_value(value_text)
        inserted_id = self.model.insert(index, value)
        snapshot = self.model.snapshot()
        self.view.animate_insert(snapshot, inserted_id, index)
        self._refresh_spins()

    def _on_update_value(self):
        if self.model.length == 0:
            return
        index = self.update_index_spin.value()
        value_text = self.update_value_edit.text().strip() or "∅"
        value = self._coerce_value(value_text)
        self.model.update_value(index, value)
        snapshot = self.model.snapshot()
        self.view.animate_update_value(snapshot, index)
        self._refresh_spins()

    def _on_delete(self):
        if self.model.length == 0:
            return
        index = self.delete_index_spin.value()

        # ① 删除前获取快照，拿到目标节点 id
        snapshot_before = self.model.snapshot()
        removed_id = snapshot_before[index]["id"]

        # ② 再做实际删除
        self.model.delete(index)
        snapshot_after = self.model.snapshot()

        # ③ 把真实 id 传给视图
        self.view.animate_delete(snapshot_after, removed_id, index)
        self._refresh_spins()

    def _handle_delete_from_view(self, index):
        if index < 0 or index >= self.model.length:
            return
        self.delete_index_spin.setValue(index)
        self._on_delete()

    def _handle_edit_from_view(self, index):
        if index < 0 or index >= self.model.length:
            return
        snapshot_before = self.model.snapshot()
        current_value = str(snapshot_before[index]["value"])
        text, ok = QInputDialog.getText(
            self,
            "Edit Value",
            f"Index {index} value:",
            text=current_value,
        )
        if not ok:
            return
        value = self._coerce_value(text.strip() or current_value)
        self.model.update_value(index, value)
        snapshot_after = self.model.snapshot()
        self.view.animate_update_value(snapshot_after, index)
        self._refresh_spins()

    def _on_clear_all_requested(self):
        self.model.clear()
        self.view.reset()
        self._refresh_spins()

    # ---------- State helpers ----------

    def _refresh_spins(self):
        length = self.model.length
        self.insert_index_spin.setMaximum(length)
        if self.insert_index_spin.value() > length:
            self.insert_index_spin.setValue(length)

        max_index = max(0, length - 1)
        for spin in (self.update_index_spin, self.delete_index_spin):
            spin.setMaximum(max_index)
            if spin.value() > max_index:
                spin.setValue(max_index)

        self._update_panel_enabled_state()

    def _on_lock_state(self, locked):
        self._panel_locked = locked
        self._update_panel_enabled_state()

    def _update_panel_enabled_state(self):
        has_items = self.model.length > 0
        locked = self._panel_locked

        self.create_btn.setDisabled(locked)
        self.append_btn.setDisabled(locked)

        self.insert_btn.setDisabled(locked)
        self.insert_index_spin.setDisabled(locked)
        self.insert_value_edit.setDisabled(locked)

        self.update_btn.setDisabled(locked or not has_items)
        self.update_index_spin.setDisabled(locked or not has_items)
        self.update_value_edit.setDisabled(locked or not has_items)

        self.delete_btn.setDisabled(locked or not has_items)
        self.delete_index_spin.setDisabled(locked or not has_items)

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

        return [ArrayController._coerce_value(part) for part in tokens]

    @staticmethod
    def _coerce_value(value):
        try:
            return int(value)
        except ValueError:
            try:
                return float(value)
            except ValueError:
                return value