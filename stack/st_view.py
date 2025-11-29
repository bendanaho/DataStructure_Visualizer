import math
from PyQt5.QtCore import QPointF, QRectF, Qt, QEvent, pyqtSignal, QEasingCurve, QVariantAnimation
from PyQt5.QtGui import QColor, QBrush, QPen, QTransform
from PyQt5.QtWidgets import (
    QGraphicsItem,
    QGraphicsObject,
    QGraphicsSimpleTextItem,
    QMenu,
)

from core.base_view import BaseStructureView


class StackView(BaseStructureView):
    """Visualizes stack nodes and popped output row."""

    clearAllRequested = pyqtSignal()

    def __init__(self, global_ctrl):
        super().__init__(global_ctrl)
        self.scene.installEventFilter(self)

        self.nodes = {}  # id -> StackNodeItem
        self.order = []  # bottom -> top
        self.popped_values = []
        self.base_pos = QPointF(-StackNodeItem.width / 2, 140)
        self.spacing = 52
        self.pop_line_limit = 26

        self.container_padding_x = 8
        self.container_padding_top = 6
        self.container_padding_bottom = 2
        self.container_extra_top = 48
        self.container_extra_bottom = 6
        self.entry_gap = 12

        self.container_item = self._create_container_item()
        self.scene.addItem(self.container_item)

        self.output_text = self._create_output_text_item()
        self.scene.addItem(self.output_text)

        self._default_scene_rect = QRectF(self.scene.sceneRect())
        self._scaled = False
        self._dragging = False

        self._update_container_geometry()
        self._update_output_text()

    def reset(self):
        self.scene.clear()
        self.nodes.clear()
        self.order.clear()
        self.popped_values.clear()
        self.scene.setSceneRect(self._default_scene_rect)
        self._scaled = False
        if self._canvas:
            self._canvas.resetTransform()

        self.container_item = self._create_container_item()
        self.scene.addItem(self.container_item)

        self.output_text = self._create_output_text_item()
        self.scene.addItem(self.output_text)

        self._update_container_geometry()
        self._update_output_text()

    def animate_push(self, stack_snapshot, pushed_info):
        node_id = pushed_info["id"]
        value = pushed_info["value"]
        node = StackNodeItem(node_id, value)
        node.setOpacity(0.0)
        self.scene.addItem(node)

        final_index = len(stack_snapshot) - 1
        target_pos = self._slot_position(final_index)
        entry_pos = self._mouth_position_for_target(target_pos)
        spawn_pos = self._spawn_position_for_target(target_pos)

        node.setPos(spawn_pos)

        path_duration = 540
        path_anim = self._move_node_through(
            node,
            [entry_pos, target_pos],
            duration=path_duration,
            easing=QEasingCurve.InOutSine,
        )
        fade_in = self.anim.fade_item(node, 0.0, 1.0, duration=path_duration)

        fly_in = self.anim.parallel(path_anim, fade_in)

        self.nodes[node_id] = node
        self.order.append(node_id)

        group = self.anim.sequential(fly_in)
        self._track_animation(group, finalizer=lambda: self._after_push(stack_snapshot))

    def animate_pop(self, stack_snapshot, popped_info):
        node_id = popped_info["id"]
        node = self.nodes.get(node_id)
        if not node:
            return

        mouth_pos = self._mouth_position_for_target(node.pos())
        exit_pos = self._exit_position_above_for_node(node)
        drift_target = self._pop_queue_target()

        path_to_exit = self._move_node_through(
            node,
            [mouth_pos, exit_pos],
            duration=420,
            easing=QEasingCurve.InOutSine,
        )
        drift = self.anim.move_item(node, drift_target, duration=360)
        fade = self.anim.fade_item(node, 1.0, 0.0, duration=360)

        seq = self.anim.sequential(
            path_to_exit,
            self.anim.parallel(drift, fade),
        )

        if node_id in self.order:
            self.order.remove(node_id)

        def _finalizer():
            self.scene.removeItem(node)
            self.nodes.pop(node_id, None)
            self._after_pop(stack_snapshot, popped_info["value"])

        self._track_animation(seq, finalizer=_finalizer)

    def relayout_stack(self, stack_snapshot):
        animations = []
        for idx, info in enumerate(reversed(stack_snapshot)):
            node_id = info["id"]
            node = self.nodes.get(node_id)
            if not node:
                node = StackNodeItem(node_id, info["value"])
                self.scene.addItem(node)
                self.nodes[node_id] = node
            target = self._slot_position(idx)
            animations.append(self.anim.move_item(node, target, duration=500))
            node.set_value(info["value"])
        for redundant_id in list(self.nodes):
            if all(item["id"] != redundant_id for item in stack_snapshot):
                node = self.nodes.pop(redundant_id)
                self.scene.removeItem(node)
        if animations:
            group = self.anim.parallel(*animations)
            self._track_animation(group, finalizer=lambda: self._refresh_layout(stack_snapshot))
        else:
            self._refresh_layout(snapshot=stack_snapshot)

    def _after_push(self, snapshot):
        self._refresh_layout(snapshot)
        self._update_output_text_position()

    def _after_pop(self, snapshot, popped_value):
        self.popped_values.append(popped_value)
        self._update_output_text()
        self._refresh_layout(snapshot)

    def _refresh_layout(self, snapshot):
        for node in self.nodes.values():
            node.setZValue(1)
        self._update_container_geometry()
        self._auto_scale_view()

    def _auto_scale_view(self, padding=80):
        if not self._canvas or self._dragging:
            return

        stack_rect = self._stack_bounds()
        if stack_rect.isNull():
            return

        content_rect = QRectF(stack_rect)
        if self.output_text.scene() is self.scene:
            text_rect = self.output_text.mapRectToScene(
                self.output_text.boundingRect()
            )
            content_rect = content_rect.united(text_rect)

        target_rect = QRectF(content_rect)
        target_rect.adjust(-padding, -padding, padding, padding)

        min_w = 600
        min_h = 400
        if target_rect.width() < min_w:
            delta = (min_w - target_rect.width()) / 2
            target_rect.adjust(-delta, 0, delta, 0)
        if target_rect.height() < min_h:
            delta = (min_h - target_rect.height()) / 2
            target_rect.adjust(0, -delta, 0, delta)

        self.scene.setSceneRect(target_rect)

        viewport = self._canvas.viewport().rect()
        if viewport.isNull():
            return

        need_zoom_out = (
            target_rect.width() > viewport.width()
            or target_rect.height() > viewport.height()
        )

        stack_center = stack_rect.center()

        self._canvas.resetTransform()
        if need_zoom_out:
            self._canvas.fitInView(target_rect, Qt.KeepAspectRatio)
            self._scaled = True
        else:
            self._canvas.centerOn(stack_center)
            self._scaled = False

    def _stack_bounds(self) -> QRectF:
        """仅返回栈节点（不含 POP 文本）的包围盒。"""
        if not self.nodes:
            return QRectF(
                self.base_pos.x(),
                self.base_pos.y() - StackNodeItem.height,
                StackNodeItem.width,
                StackNodeItem.height,
            )

        bounds = None
        for node in self.nodes.values():
            node_rect = node.mapRectToScene(node.boundingRect())
            bounds = node_rect if bounds is None else bounds.united(node_rect)
        return bounds

    def on_canvas_ready(self):
        """在画布绑定完成后立即居中一次，避免初始状态偏移。"""
        self._update_output_text_position()
        self._auto_scale_view()

    def _update_output_text(self):
        lines = self._wrap_popped_values()
        if not lines:
            text = "POP: —"
        else:
            text = "POP:" + "\n".join(lines)
        self.output_text.setText(text)
        self._update_output_text_position()
        self._auto_scale_view()

    def _update_output_text_position(self):
        stack_top = self._stack_top_y()
        anchor = QPointF(
            self.base_pos.x() + StackNodeItem.width + 80,
            stack_top - 40,
        )
        rect = self.output_text.boundingRect()
        self.output_text.setPos(anchor.x(), anchor.y() - rect.height())

    def _wrap_popped_values(self):
        if not self.popped_values:
            return []
        limit = max(10, self.pop_line_limit)
        lines = []
        current = ""
        for token in map(str, self.popped_values):
            token = token.strip()
            addition = token if not current else f" {token}"
            if len(current) + len(addition) > limit and current:
                lines.append(current)
                current = token
            else:
                current = current + addition if current else token
        if current:
            lines.append(current)
        return lines

    def _clear_pop_history(self):
        if not self.popped_values:
            return
        self.popped_values.clear()
        self._update_output_text()

    def _cancel_pending_animations(self):
        if not getattr(self, "_running", None):
            return
        for anim in list(self._running):
            anim.stop()
        self._running.clear()
        self.unlock_interactions()

    def _show_background_menu(self, screen_pos):
        if isinstance(screen_pos, QPointF):
            screen_pos = screen_pos.toPoint()

        menu = QMenu()
        clear_pop_action = menu.addAction("Clear Pop")
        clear_all_action = menu.addAction("Clear All")
        chosen = menu.exec_(screen_pos)

        if chosen == clear_pop_action:
            self._clear_pop_history()
        elif chosen == clear_all_action:
            self._cancel_pending_animations()
            self._clear_pop_history()
            self.clearAllRequested.emit()

    def eventFilter(self, watched, event):
        if watched is self.scene and event.type() == QEvent.GraphicsSceneContextMenu:
            item = self.scene.itemAt(event.scenePos(), QTransform())
            if item is None:
                self._show_background_menu(event.screenPos())
                event.accept()
                return True
        return super().eventFilter(watched, event)

    def _create_output_text_item(self):
        item = QGraphicsSimpleTextItem()
        item.setBrush(QColor("#ef6c00"))
        font = item.font()
        font.setPointSize(16)
        font.setBold(True)
        item.setFont(font)
        item.setZValue(5)
        return item

    def _create_container_item(self):
        item = StackContainerItem()
        item.setZValue(0)
        return item

    def _update_container_geometry(self):
        if not self.container_item:
            return

        bounds = self._stack_bounds()
        width = bounds.width() + self.container_padding_x * 2
        height = (
            bounds.height()
            + self.container_padding_top
            + self.container_padding_bottom
            + self.container_extra_top
            + self.container_extra_bottom
        )
        left_x = bounds.left() - self.container_padding_x
        top_y = bounds.top() - self.container_padding_top - self.container_extra_top

        self.container_item.set_geometry(width, height)
        self.container_item.setPos(left_x, top_y)

    def _stack_top_y(self):
        if not self.nodes:
            return self.base_pos.y() - StackNodeItem.height
        return min(node.y() for node in self.nodes.values())

    def _slot_position(self, index_from_bottom: int) -> QPointF:
        return QPointF(
            self.base_pos.x(),
            self.base_pos.y() - StackNodeItem.height - index_from_bottom * self.spacing,
        )

    def _top_clearance(self):
        return self.container_padding_top + self.container_extra_top

    def _spawn_position_for_target(self, target_pos: QPointF) -> QPointF:
        return QPointF(
            target_pos.x(),
            target_pos.y() - self._top_clearance() - StackNodeItem.height - self.entry_gap,
        )

    def _mouth_position_for_target(self, target_pos: QPointF) -> QPointF:
        return QPointF(
            target_pos.x(),
            target_pos.y() - self.container_extra_top,
        )

    def _exit_position_above_for_node(self, node: QGraphicsObject) -> QPointF:
        top_y = node.y()
        container_top = top_y - self._top_clearance()
        return QPointF(
            node.x(),
            container_top - StackNodeItem.height - self.entry_gap,
        )

    def _pop_queue_target(self) -> QPointF:
        return QPointF(
            self.base_pos.x() + StackNodeItem.width + 40,
            self.base_pos.y() - StackNodeItem.height - 40,
        )

    def _move_node_through(
        self,
        node: QGraphicsObject,
        waypoints: list[QPointF],
        duration: int,
        easing: QEasingCurve = QEasingCurve.InOutCubic,
    ):
        if not waypoints:
            return self.anim.move_item(node, node.pos(), duration=duration)

        points = [node.pos()] + waypoints
        seg_lengths = [
            self._distance_between(points[i], points[i + 1])
            for i in range(len(points) - 1)
        ]
        total_length = sum(seg_lengths) or 1.0

        animation = QVariantAnimation(self)
        animation.setDuration(duration)
        animation.setStartValue(0.0)
        animation.setEndValue(1.0)
        animation.setEasingCurve(easing)

        def _update(value: float):
            traveled = value * total_length
            accumulated = 0.0
            for idx, seg_len in enumerate(seg_lengths):
                next_accum = accumulated + seg_len
                if traveled <= next_accum or idx == len(seg_lengths) - 1:
                    span = seg_len or 1.0
                    local_t = (traveled - accumulated) / span if span else 0.0
                    pos = self._lerp_point(points[idx], points[idx + 1], local_t)
                    node.setPos(pos)
                    break
                accumulated = next_accum

        animation.valueChanged.connect(_update)
        animation.finished.connect(lambda: node.setPos(points[-1]))
        return animation

    def _lerp_point(self, a: QPointF, b: QPointF, t: float) -> QPointF:
        return QPointF(
            a.x() + (b.x() - a.x()) * t,
            a.y() + (b.y() - a.y()) * t,
        )

    def _distance_between(self, a: QPointF, b: QPointF) -> float:
        return math.hypot(b.x() - a.x(), b.y() - a.y())


class StackNodeItem(QGraphicsObject):
    width = 120
    height = 48

    def __init__(self, node_id, value):
        super().__init__()
        self.node_id = node_id
        self._value = str(value)
        self.fill_color = QColor("#e9e9ef")
        self.stroke_color = QColor("#4a4a52")
        self.text_color = QColor("#1f1f24")
        self.setCacheMode(QGraphicsItem.DeviceCoordinateCache)

    def boundingRect(self):
        return self._rect()

    def _rect(self):
        return QRectF(0, 0, self.width, self.height)

    def paint(self, painter, option, widget=None):
        painter.setRenderHint(painter.Antialiasing)
        painter.setPen(QPen(self.stroke_color, 2))
        painter.setBrush(QBrush(self.fill_color))
        painter.drawRoundedRect(self._rect(), 10, 10)

        font = painter.font()
        font.setPointSize(14)
        painter.setFont(font)
        painter.setPen(self.text_color)
        painter.drawText(self._rect(), Qt.AlignCenter, self._value)

    def set_value(self, value):
        self._value = str(value)
        self.update()

    def setFillColor(self, color: QColor):
        self.fill_color = QColor(color)
        self.update()

    def setStrokeColor(self, color: QColor):
        self.stroke_color = QColor(color)
        self.update()


class StackContainerItem(QGraphicsObject):
    def __init__(self):
        super().__init__()
        self._rect = QRectF(0, 0, StackNodeItem.width + 48, StackNodeItem.height * 4)
        self.stroke_color = QColor("#000000")
        self.stroke_width = 3

    def boundingRect(self):
        return self._rect

    def set_geometry(self, width, height):
        new_rect = QRectF(0, 0, width, height)
        if new_rect == self._rect:
            return
        self.prepareGeometryChange()
        self._rect = new_rect
        self.update()

    def paint(self, painter, option, widget=None):
        painter.setRenderHint(painter.Antialiasing)
        painter.setBrush(Qt.NoBrush)

        inner = self._rect.adjusted(
            self.stroke_width / 2,
            self.stroke_width / 2,
            -self.stroke_width / 2,
            -self.stroke_width / 2,
        )

        pen = QPen(
            self.stroke_color,
            self.stroke_width,
            Qt.SolidLine,
            Qt.RoundCap,
            Qt.RoundJoin,
        )
        painter.setPen(pen)
        painter.drawLine(inner.topLeft(), inner.bottomLeft())
        painter.drawLine(inner.bottomLeft(), inner.bottomRight())
        painter.drawLine(inner.bottomRight(), inner.topRight())