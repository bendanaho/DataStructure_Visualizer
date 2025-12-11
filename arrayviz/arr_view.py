from PyQt5.QtCore import QEvent, QPointF, QRectF, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QBrush, QPen, QTransform
from PyQt5.QtWidgets import (
    QGraphicsItem,
    QGraphicsObject,
    QGraphicsSimpleTextItem,
    QMenu,
)

from core.base_view import BaseStructureView


class ArrayView(BaseStructureView):
    deleteRequested = pyqtSignal(int)
    editRequested = pyqtSignal(int)
    clearAllRequested = pyqtSignal()

    def __init__(self, global_ctrl):
        super().__init__(global_ctrl)
        self.scene.installEventFilter(self)

        self.cells = {}
        self.order = []
        self.index_labels = {}
        self.slot_items = {}

        self.base_origin = QPointF(-360, -ArrayCellItem.height / 2)
        self.slot_gap = 0  # 无缝排列
        self.initial_capacity = 4
        self.capacity = self.initial_capacity

        self._default_scene_rect = QRectF(self.scene.sceneRect())
        self._scaled = False

        self._rebuild_slots()
        self._auto_scale_view()

    def bind_canvas(self, view):
        super().bind_canvas(view)
        self._auto_scale_view()

    # ---------- Public API ----------

    def reset(self):
        self.scene.clear()
        self.cells.clear()
        self.order.clear()
        self.index_labels.clear()
        self.slot_items.clear()

        self.capacity = self.initial_capacity
        self._rebuild_slots()
        self._auto_scale_view()

    def animate_build(self, snapshot, speed_scale: float = 1.0):
        self.reset()
        self._ensure_capacity(len(snapshot))
        if not snapshot:
            self._finalize_snapshot(snapshot)
            return

        speed_scale = max(0.1, float(speed_scale))

        def scaled(base_ms: int) -> int:
            return max(1, int(base_ms / speed_scale))

        sequential = self.anim.sequential()
        for idx, info in enumerate(snapshot):
            cell = self._create_cell_item(info["id"], info["value"])
            target = self._slot_position(idx)
            spawn = self._spawn_position(idx)
            cell.setPos(spawn)
            cell.setOpacity(0.0)

            drop = self.anim.move_item(cell, target, duration=scaled(520))
            fade = self.anim.fade_item(cell, 0.0, 1.0, duration=scaled(520))
            sequential.addAnimation(self.anim.parallel(drop, fade))

        sequential.addAnimation(self.anim.pause(scaled(120)))
        self._track_animation(
            sequential, finalizer=lambda: self._finalize_snapshot(snapshot)
        )

    def animate_insert(self, snapshot, inserted_id, index):
        if not snapshot:
            self.reset()
            return

        self._ensure_capacity(len(snapshot))

        # ---------- 1. 逐个后移 ----------
        shift_ids = [
            info["id"]
            for info in snapshot[index + 1 :]
            if info["id"] in self.cells
        ]
        shift_count = len(shift_ids)
        shift_duration = self._calc_shift_duration(shift_count)

        shift_sequence = self.anim.sequential()
        for node_id in reversed(shift_ids):
            cell = self.cells[node_id]
            current_idx = self.order.index(node_id)
            target_idx = current_idx + 1
            shift_sequence.addAnimation(
                self.anim.move_item(
                    cell,
                    self._slot_position(target_idx),
                    duration=shift_duration,
                )
            )

        # ---------- 2. 创建或更新新元素 ----------
        new_info = snapshot[index]
        cell = self.cells.get(inserted_id)
        if not cell:
            cell = self._create_cell_item(inserted_id, new_info["value"])
            cell.setOpacity(0.0)
            cell.setPos(self._spawn_position(index))
        else:
            cell.set_value(new_info["value"])

        drop = self.anim.move_item(cell, self._slot_position(index), duration=420)
        fade = self.anim.fade_item(cell, cell.opacity(), 1.0, duration=420)
        insert_anim = self.anim.parallel(drop, fade)

        highlight = self.anim.flash_brush(
            setter=cell.setFillColor,
            start_color=cell.fillColor,
            end_color=QColor("#ffd54f"),
            duration=420,
            loops=2,
        )

        # ---------- 3. 串接：后移 -> 插入 -> 闪烁 ----------
        sequence = self.anim.sequential()
        if shift_count > 0:
            sequence.addAnimation(shift_sequence)
        sequence.addAnimation(insert_anim)
        sequence.addAnimation(highlight)

        self._track_animation(
            sequence,
            finalizer=lambda: self._finalize_snapshot(snapshot),
        )

    def animate_delete(self, snapshot, removed_id, index):
        self._ensure_capacity(len(snapshot))

        removed_cell = self.cells.get(removed_id)
        if not removed_cell:
            # 若场景中已不存在该元素，直接做最终收尾
            self._finalize_snapshot(snapshot)
            return

        # ---------- 1. 红色闪烁 ----------
        blink = self.anim.flash_brush(
            setter=removed_cell.setFillColor,
            start_color=removed_cell.fillColor,
            end_color=QColor("#ff7043"),
            duration=360,
            loops=2,
        )

        # ---------- 2. 移出动画 ----------
        exit_target = self._spawn_position(index)
        lift = self.anim.move_item(removed_cell, exit_target, duration=360)
        fade = self.anim.fade_item(removed_cell, 1.0, 0.0, duration=360)
        exit_anim = self.anim.parallel(lift, fade)

        # ---------- 3. 逐个左移 ----------
        shift_ids = [
            info["id"]
            for info in snapshot[index:]
            if info["id"] in self.cells and info["id"] != removed_id
        ]
        shift_count = len(shift_ids)
        shift_duration = self._calc_shift_duration(shift_count)

        shift_sequence = self.anim.sequential()
        for node_id in shift_ids:
            cell = self.cells[node_id]
            current_idx = self.order.index(node_id)
            target_idx = current_idx - 1
            shift_sequence.addAnimation(
                self.anim.move_item(
                    cell,
                    self._slot_position(target_idx),
                    duration=shift_duration,
                )
            )

        # ---------- 4. 串接 ----------
        sequence = self.anim.sequential()
        sequence.addAnimation(blink)
        sequence.addAnimation(exit_anim)
        if shift_count > 0:
            sequence.addAnimation(shift_sequence)

        self._track_animation(
            sequence,
            finalizer=lambda: self._finalize_snapshot(snapshot),
        )

    def animate_update_value(self, snapshot, index):
        self._ensure_capacity(len(snapshot))
        if index < 0 or index >= len(snapshot):
            self.update_values(snapshot)
            return

        target_id = snapshot[index]["id"]
        cell = self.cells.get(target_id)
        if not cell:
            self.update_values(snapshot)
            return

        cell.set_value(snapshot[index]["value"])
        pulse = self.anim.flash_brush(
            setter=cell.setFillColor,
            start_color=cell.fillColor,
            end_color=QColor("#4dd0e1"),
            duration=360,
            loops=2,
        )
        self._track_animation(
            pulse, finalizer=lambda: self._finalize_snapshot(snapshot)
        )

    def update_values(self, snapshot):
        self._ensure_capacity(len(snapshot))
        for idx, info in enumerate(snapshot):
            item = self.cells.get(info["id"])
            if not item:
                item = self._create_cell_item(info["id"], info["value"])
                item.setOpacity(1.0)
            item.set_value(info["value"])
            item.setPos(self._slot_position(idx))
        self._finalize_snapshot(snapshot)

    def index_of(self, node_id):
        return self.order.index(node_id) if node_id in self.order else -1

    # ---------- Internal helpers ----------
    def _calc_shift_duration(self, shift_count: int) -> int:
        """
        根据需要移动的元素个数决定单个元素的移动时间。
        元素越多，单个移动越快（下限 180ms，上限 520ms）。
        """
        shift_count = max(1, shift_count)
        return max(120, int(520 - 35 * (shift_count - 1)))

    def _create_cell_item(self, node_id, value):
        cell = ArrayCellItem(node_id, value)
        cell.contextDelete.connect(self._handle_cell_delete)
        cell.contextEdit.connect(self._handle_cell_edit)
        self.scene.addItem(cell)
        self.cells[node_id] = cell
        return cell

    def _handle_cell_delete(self, node_id):
        idx = self.index_of(node_id)
        if idx != -1:
            self.deleteRequested.emit(idx)

    def _handle_cell_edit(self, node_id):
        idx = self.index_of(node_id)
        if idx != -1:
            self.editRequested.emit(idx)

    def _slot_position(self, index: int) -> QPointF:
        step = ArrayCellItem.width + self.slot_gap
        x = self.base_origin.x() + index * step
        y = self.base_origin.y()
        return QPointF(x, y)

    def _spawn_position(self, index: int) -> QPointF:
        target = self._slot_position(index)
        return QPointF(target.x(), target.y() - (ArrayCellItem.height + 110))

    def _finalize_snapshot(self, snapshot):
        keep_ids = {info["id"] for info in snapshot}
        for node_id in list(self.cells.keys()):
            if node_id not in keep_ids:
                item = self.cells.pop(node_id)
                if item.scene():
                    self.scene.removeItem(item)

        self.order = [info["id"] for info in snapshot]
        index_map = {node_id: idx for idx, node_id in enumerate(self.order)}
        for info in snapshot:
            item = self.cells.get(info["id"])
            if item:
                idx = index_map[info["id"]]
                item.set_value(info["value"])
                item.setPos(self._slot_position(idx))
                item.setZValue(2)

        self._update_index_labels()
        self._auto_scale_view()

    def _update_index_labels(self):
        count = len(self.order)
        for idx in list(self.index_labels.keys()):
            if idx >= count:
                label = self.index_labels.pop(idx)
                if label.scene():
                    self.scene.removeItem(label)

        for idx in range(count):
            label = self.index_labels.get(idx)
            if label is None:
                label = QGraphicsSimpleTextItem(str(idx))
                label.setBrush(QColor("#90a4ae"))
                font = label.font()
                font.setPointSize(12)
                label.setFont(font)
                label.setZValue(1)
                self.scene.addItem(label)
                self.index_labels[idx] = label
            else:
                label.setText(str(idx))
            self._position_index_label(idx, label)

    def _position_index_label(self, index, label: QGraphicsSimpleTextItem):
        slot = self._slot_position(index)
        rect = label.boundingRect()
        x = slot.x() + ArrayCellItem.width / 2 - rect.width() / 2
        y = slot.y() + ArrayCellItem.height + 8
        label.setPos(x, y)

    def _ensure_capacity(self, required: int):
        if required <= self.capacity:
            return
        while self.capacity < required:
            self.capacity *= 2
        self._rebuild_slots()

    def _rebuild_slots(self):
        # 创建或更新 slot 图元
        for idx in range(self.capacity):
            slot = self.slot_items.get(idx)
            if slot is None:
                slot = self._create_slot_item(idx)
                self.slot_items[idx] = slot
                self.scene.addItem(slot)
            slot.setPos(self._slot_position(idx))

        # 移除超出容量的 slot（通常用不到）
        for idx in list(self.slot_items.keys()):
            if idx >= self.capacity:
                slot = self.slot_items.pop(idx)
                if slot.scene():
                    self.scene.removeItem(slot)

    def _create_slot_item(self, index: int):
        slot = ArraySlotItem()
        slot.setZValue(-1)
        return slot

    def _auto_scale_view(self, padding=80):
        if not self._canvas:
            return

        items_rect = self.scene.itemsBoundingRect()
        if items_rect.isNull():
            items_rect = QRectF(self._default_scene_rect)

        target = QRectF(items_rect)
        target.adjust(-padding, -padding, padding, padding)
        self.scene.setSceneRect(target)

        viewport = self._canvas.viewport().rect()
        if viewport.isNull():
            return

        self._canvas.resetTransform()
        need_zoom = (
            target.width() > viewport.width()
            or target.height() > viewport.height()
        )
        if need_zoom:
            self._canvas.fitInView(target, Qt.KeepAspectRatio)
            self._scaled = True
        else:
            self._canvas.centerOn(items_rect.center())
            self._scaled = False

    def _show_background_menu(self, screen_pos):
        if isinstance(screen_pos, QPointF):
            screen_pos = screen_pos.toPoint()
        menu = QMenu()
        clear_action = menu.addAction("Clear Array")
        chosen = menu.exec_(screen_pos)
        if chosen == clear_action:
            self.clearAllRequested.emit()

    def eventFilter(self, watched, event):
        if watched is self.scene and event.type() == QEvent.GraphicsSceneContextMenu:
            item = self.scene.itemAt(event.scenePos(), QTransform())
            if item is None:
                self._show_background_menu(event.screenPos())
                event.accept()
                return True
        return super().eventFilter(watched, event)


class ArrayCellItem(QGraphicsObject):
    contextDelete = pyqtSignal(int)
    contextEdit = pyqtSignal(int)

    width = 96
    height = 64

    def __init__(self, node_id, value):
        super().__init__()
        self.node_id = node_id
        self._value = str(value)
        self.fillColor = QColor("#b8b8d6")
        self.strokeColor = QColor("#4a4a52")
        self.textColor = QColor("#1f1f24")
        self.setZValue(2)
        self.setAcceptedMouseButtons(Qt.LeftButton | Qt.RightButton)
        self.setCacheMode(QGraphicsItem.DeviceCoordinateCache)

    def boundingRect(self):
        return QRectF(0, 0, self.width, self.height)

    def paint(self, painter, option, widget=None):
        painter.setRenderHint(painter.Antialiasing)
        painter.setPen(QPen(self.strokeColor, 2))
        painter.setBrush(QBrush(self.fillColor))
        painter.drawRect(self.boundingRect())

        font = painter.font()
        font.setPointSize(14)
        painter.setFont(font)
        painter.setPen(self.textColor)
        painter.drawText(self.boundingRect(), Qt.AlignCenter, self._value)

    def set_value(self, value):
        self._value = str(value)
        self.update()

    def setFillColor(self, color: QColor):
        self.fillColor = QColor(color)
        self.update()

    def setStrokeColor(self, color: QColor):
        self.strokeColor = QColor(color)
        self.update()

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.contextEdit.emit(self.node_id)
        super().mouseDoubleClickEvent(event)

    def contextMenuEvent(self, event):
        menu = QMenu()
        edit_action = menu.addAction("Edit Value")
        delete_action = menu.addAction("Delete")
        chosen = menu.exec_(event.screenPos())
        if chosen == edit_action:
            self.contextEdit.emit(self.node_id)
        elif chosen == delete_action:
            self.contextDelete.emit(self.node_id)


class ArraySlotItem(QGraphicsObject):
    width = ArrayCellItem.width
    height = ArrayCellItem.height

    def __init__(self):
        super().__init__()
        self.fillColor = QColor("#f6f6fd")
        self.strokeColor = QColor("#74828a")

    def boundingRect(self):
        return QRectF(0, 0, self.width, self.height)

    def paint(self, painter, option, widget=None):
        painter.setRenderHint(painter.Antialiasing)
        painter.setPen(QPen(self.strokeColor, 1.6))
        painter.setBrush(QBrush(self.fillColor))
        painter.drawRect(self.boundingRect())


class ArrayViewWithPersistence(ArrayView):
    saveRequested = pyqtSignal()
    loadRequested = pyqtSignal()

    def _show_background_menu(self, screen_pos):
        if isinstance(screen_pos, QPointF):
            screen_pos = screen_pos.toPoint()

        menu = QMenu()
        open_action = menu.addAction("Open From File…")
        save_action = menu.addAction("Save To File…")
        menu.addSeparator()
        clear_action = menu.addAction("Clear Array")
        chosen = menu.exec_(screen_pos)

        if chosen == open_action:
            self.loadRequested.emit()
        elif chosen == save_action:
            self.saveRequested.emit()
        elif chosen == clear_action:
            self.clearAllRequested.emit()