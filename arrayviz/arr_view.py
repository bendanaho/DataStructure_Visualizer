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

        self.base_origin = QPointF(-360, -ArrayCellItem.height / 2)
        self.slot_gap = 24
        self.container_padding_x = 14
        self.container_padding_top = 18
        self.container_padding_bottom = 20
        self.min_visible_capacity = 8

        self.container_item = self._create_container_item()
        self.scene.addItem(self.container_item)

        self._default_scene_rect = QRectF(self.scene.sceneRect())
        self._scaled = False

        self._update_container_geometry()
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

        self.container_item = self._create_container_item()
        self.scene.addItem(self.container_item)
        self._update_container_geometry()
        self._auto_scale_view()

    def animate_build(self, snapshot):
        self.reset()
        if not snapshot:
            self._finalize_snapshot(snapshot)
            return

        sequential = self.anim.sequential()
        for idx, info in enumerate(snapshot):
            cell = self._create_cell_item(info["id"], info["value"])
            target = self._slot_position(idx)
            spawn = self._spawn_position(idx)
            cell.setPos(spawn)
            cell.setOpacity(0.0)

            drop = self.anim.move_item(cell, target, duration=520)
            fade = self.anim.fade_item(cell, 0.0, 1.0, duration=520)
            sequential.addAnimation(self.anim.parallel(drop, fade))

        sequential.addAnimation(self.anim.pause(120))
        self._track_animation(
            sequential, finalizer=lambda: self._finalize_snapshot(snapshot)
        )

    def animate_insert(self, snapshot, inserted_id, index):
        if not snapshot:
            self.reset()
            return

        new_info = snapshot[index]
        cell = self.cells.get(inserted_id)
        if not cell:
            cell = self._create_cell_item(inserted_id, new_info["value"])
            cell.setOpacity(0.0)
            cell.setPos(self._spawn_position(index))
        else:
            cell.set_value(new_info["value"])

        motions = []
        for idx, info in enumerate(snapshot):
            item = self.cells.get(info["id"])
            if not item:
                item = self._create_cell_item(info["id"], info["value"])
                item.setOpacity(0.0)
                item.setPos(self._slot_position(idx))
            item.set_value(info["value"])
            motions.append(
                self.anim.move_item(item, self._slot_position(idx), duration=520)
            )

        fade = self.anim.fade_item(cell, cell.opacity(), 1.0, duration=520)
        highlight = self.anim.flash_brush(
            setter=cell.setFillColor,
            start_color=cell.fillColor,
            end_color=QColor("#ffd54f"),
            duration=420,
            loops=2,
        )

        group = self.anim.parallel(*(motions + [fade]))
        sequence = self.anim.sequential(group, highlight)
        self._track_animation(
            sequence, finalizer=lambda: self._finalize_snapshot(snapshot)
        )

    def animate_delete(self, snapshot, removed_id, index):
        removed_cell = self.cells.get(removed_id)
        fade_out = (
            self.anim.fade_item(removed_cell, 1.0, 0.0, duration=360)
            if removed_cell
            else None
        )

        motions = []
        for idx, info in enumerate(snapshot):
            item = self.cells.get(info["id"])
            if not item:
                item = self._create_cell_item(info["id"], info["value"])
                item.setPos(self._slot_position(idx))
            item.set_value(info["value"])
            motions.append(
                self.anim.move_item(item, self._slot_position(idx), duration=480)
            )

        group = self.anim.parallel(*(motions + ([fade_out] if fade_out else [])))
        self._track_animation(
            group, finalizer=lambda: self._finalize_snapshot(snapshot)
        )

    def animate_update_value(self, snapshot, index):
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
        for info in snapshot:
            item = self.cells.get(info["id"])
            if item:
                item.set_value(info["value"])
                item.setZValue(2)

        self._update_index_labels()
        self._update_container_geometry()
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
                label.setZValue(0)
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

    def _visible_slot_count(self):
        return max(self.min_visible_capacity, len(self.order), 1)

    def _update_container_geometry(self):
        visible_slots = self._visible_slot_count()
        content_width = (
            visible_slots * ArrayCellItem.width
            + max(0, visible_slots - 1) * self.slot_gap
        )
        content_height = (
            ArrayCellItem.height
            + self.container_padding_top
            + self.container_padding_bottom
        )

        self.container_item.set_geometry(
            content_width + self.container_padding_x * 2,
            content_height,
        )
        self.container_item.setPos(
            self.base_origin.x() - self.container_padding_x,
            self.base_origin.y() - self.container_padding_top,
        )

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

    def _create_container_item(self):
        item = ArrayContainerItem()
        item.setZValue(-5)
        return item


class ArrayCellItem(QGraphicsObject):
    contextDelete = pyqtSignal(int)
    contextEdit = pyqtSignal(int)

    width = 96
    height = 64

    def __init__(self, node_id, value):
        super().__init__()
        self.node_id = node_id
        self._value = str(value)
        self.fillColor = QColor("#5c6bc0")
        self.strokeColor = QColor("#283593")
        self.textColor = QColor("#fafafa")
        self.setZValue(2)
        self.setAcceptedMouseButtons(Qt.LeftButton | Qt.RightButton)
        self.setCacheMode(QGraphicsItem.DeviceCoordinateCache)

    def boundingRect(self):
        return QRectF(0, 0, self.width, self.height)

    def paint(self, painter, option, widget=None):
        painter.setRenderHint(painter.Antialiasing)
        painter.setPen(QPen(self.strokeColor, 2))
        painter.setBrush(QBrush(self.fillColor))
        painter.drawRoundedRect(self.boundingRect(), 12, 12)

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


class ArrayContainerItem(QGraphicsObject):
    def __init__(self):
        super().__init__()
        self._rect = QRectF(0, 0, 400, 120)
        self._pen = QPen(QColor("#90a4ae"), 2)
        self._pen.setJoinStyle(Qt.RoundJoin)
        self._pen.setCapStyle(Qt.RoundCap)
        self._brush = QBrush(QColor(255, 255, 255, 18))

    def boundingRect(self):
        return self._rect

    def set_geometry(self, width, height):
        rect = QRectF(0, 0, width, height)
        if rect == self._rect:
            return
        self.prepareGeometryChange()
        self._rect = rect
        self.update()

    def paint(self, painter, option, widget=None):
        painter.setRenderHint(painter.Antialiasing)
        painter.setPen(self._pen)
        painter.setBrush(self._brush)
        painter.drawRoundedRect(self._rect, 16, 16)