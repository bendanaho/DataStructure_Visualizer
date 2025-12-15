import math
import random
from typing import Dict, List, Optional, Tuple

from PyQt5.QtCore import (
    QPointF,
    Qt,
    pyqtSignal,
    QVariantAnimation,
    QRectF,
    QEvent,
    QTimer,
)
from PyQt5.QtGui import (
    QColor,
    QBrush,
    QPainterPath,
    QPen,
    QFont,
    QFontMetrics,
)
from PyQt5.QtWidgets import (
    QGraphicsItem,
    QGraphicsObject,
    QGraphicsPathItem,
    QMenu,
    QGraphicsSimpleTextItem,
)

from core.base_view import BaseStructureView


class DoublyLinkedListView(BaseStructureView):
    deleteRequested = pyqtSignal(int)
    editRequested = pyqtSignal(int)
    clearAllRequested = pyqtSignal()

    def __init__(self, global_ctrl):
        super().__init__(global_ctrl)
        self.scene.installEventFilter(self)

        self.node_items: Dict[int, DoublyLinkedListNodeItem] = {}
        self.order: List[int] = []
        self.arrow_items: Dict[Tuple[int, int], ArrowItem] = {}
        self._dragging = False

        self._head_label = self._create_head_label()
        self.scene.addItem(self._head_label)

    # ------------------------------------------------------------------ Scene lifecycle

    def bind_canvas(self, canvas):
        super().bind_canvas(canvas)
        if self._canvas:
            QTimer.singleShot(0, self._auto_scale_view)

    def reset(self):
        self.scene.clear()
        self.node_items.clear()
        self.order.clear()
        self.arrow_items.clear()

        self._head_label = self._create_head_label()
        self.scene.addItem(self._head_label)

    # ------------------------------------------------------------------ Animations

    def animate_build(self, nodes, speed_scale: float = 1.0):
        self.reset()
        if not nodes:
            return

        speed_scale = max(0.1, float(speed_scale))

        def scaled(ms: int) -> int:
            return max(1, int(ms / speed_scale))

        seq = self.anim.sequential()

        for idx, info in enumerate(nodes):
            target = self._pick_sparse_position(index=idx)
            node_item = DoublyLinkedListNodeItem(info["id"], info["value"])
            node_item.setOpacity(0.0)
            node_item.setPos(QPointF(target.x(), target.y() - 160))
            self._wire_node(node_item)
            self.scene.addItem(node_item)
            self.node_items[info["id"]] = node_item
            self.order.append(info["id"])

            fade = self.anim.fade_item(node_item, 0.0, 1.0, duration=scaled(600))
            drop = self.anim.move_item(node_item, target, duration=scaled(800))
            seq.addAnimation(self.anim.parallel(fade, drop))

        self.order = [node["id"] for node in nodes]
        self._auto_scale_view()
        seq.addAnimation(self.anim.pause(scaled(160)))
        self._track_animation(seq, finalizer=self._refresh_connectivity)

    def animate_insert(self, nodes, inserted_id, index):
        new_info = next((node for node in nodes if node["id"] == inserted_id), None)
        if new_info is None:
            return

        target = self._pick_sparse_position(index=index)
        new_node = DoublyLinkedListNodeItem(new_info["id"], new_info["value"])
        new_node.setOpacity(0.0)
        new_node.setPos(QPointF(target.x(), target.y() - 160))
        self._wire_node(new_node)
        self.scene.addItem(new_node)
        self.node_items[new_node.node_id] = new_node
        self._auto_scale_view()

        predecessor_id = self.order[index - 1] if index > 0 else None
        successor_id = self.order[index] if index < len(self.order) else None

        traversal = self._build_traversal_anim(index)
        fade_in = self.anim.parallel(
            self.anim.move_item(new_node, target, duration=650),
            self.anim.fade_item(new_node, 0.0, 1.0, duration=650),
        )
        flash_new = self.anim.flash_brush(
            setter=new_node.setFillColor,
            start_color=new_node.fillColor,
            end_color=QColor("#ff8a65"),
            duration=420,
            loops=2,
        )

        new_next_anim = self._animate_new_arrow_link(new_node, successor_id, role="next")
        new_prev_anim = self._animate_new_arrow_link(new_node, predecessor_id, role="prev")

        pred_transition = None
        pred_restore = None
        if predecessor_id is not None:
            if successor_id is not None and (predecessor_id, successor_id) in self.arrow_items:
                pred_transition, pred_restore = self._build_arrow_transition(
                    predecessor_id, successor_id, new_node.node_id, role="next"
                )
            else:
                pred_transition = self._animate_new_arrow_link(
                    self.node_items.get(predecessor_id),
                    new_node.node_id,
                    role="next",
                    duration=520,
                )

        succ_transition = None
        succ_restore = None
        if successor_id is not None:
            old_prev = predecessor_id
            if old_prev is not None and (successor_id, old_prev) in self.arrow_items:
                succ_transition, succ_restore = self._build_arrow_transition(
                    successor_id, old_prev, new_node.node_id, role="prev"
                )
            else:
                succ_transition = self._animate_new_arrow_link(
                    self.node_items.get(successor_id),
                    new_node.node_id,
                    role="prev",
                    duration=520,
                )

        self_links = self.anim.sequential(
            new_next_anim if new_next_anim else self.anim.pause(80),
            new_prev_anim if new_prev_anim else self.anim.pause(80),
        )

        neighbor_anims = []
        if pred_transition:
            neighbor_anims.append(pred_transition)
        elif predecessor_id is not None:
            neighbor_anims.append(self.anim.pause(80))

        if succ_transition:
            neighbor_anims.append(succ_transition)
        elif successor_id is not None:
            neighbor_anims.append(self.anim.pause(80))

        neighbor_phase = (
            self.anim.sequential(*neighbor_anims) if neighbor_anims else self.anim.pause(80)
        )

        combined = self.anim.sequential(
            traversal,
            fade_in,
            flash_new,
            self_links,
            neighbor_phase,
        )

        restore_callbacks = [cb for cb in (pred_restore, succ_restore) if cb]

        def _finalizer():
            self._finalize_insert(nodes, new_node, index)
            for cb in restore_callbacks:
                cb()

        self._track_animation(combined, finalizer=_finalizer)

    def animate_delete(self, nodes, removed_id, index):
        target_node = self.node_items.get(removed_id)
        if not target_node:
            return

        traversal = self._build_traversal_anim(index)

        # 获取逻辑上的前驱和后继 ID (基于旧的 order)
        predecessor_id = self.order[index - 1] if index > 0 else None
        successor_id = self.order[index + 1] if index + 1 < len(self.order) else None

        flash = self.anim.flash_brush(
            setter=target_node.setFillColor,
            start_color=target_node.fillColor,
            end_color=QColor("#ff5252"),
            duration=420,
            loops=2,
        )

        # --- 箭头处理逻辑 ---

        forward_transition = None
        forward_restore = None

        backward_transition = None
        backward_restore = None

        # 收集需要淡出的额外箭头（除了从被删除节点出发的箭头外）
        extra_fade_arrows = []

        # 1. 前驱节点的 next 指针
        if predecessor_id is not None:
            if successor_id is not None:
                # 正常情况：前驱 -> 后继
                forward_transition, forward_restore = self._build_arrow_transition(
                    predecessor_id, removed_id, successor_id, role="next"
                )
            else:
                # 尾节点被删：前驱 -> None (箭头应淡出)
                arrow = self.arrow_items.get((predecessor_id, removed_id))
                if arrow:
                    extra_fade_arrows.append(arrow)
                    # 从字典中移除，防止 _fade_outgoing_arrows 重复处理或干扰
                    self.arrow_items.pop((predecessor_id, removed_id), None)

        # 2. 后继节点的 prev 指针
        if successor_id is not None:
            if predecessor_id is not None:
                # 正常情况：后继 -> 前驱
                backward_transition, backward_restore = self._build_arrow_transition(
                    successor_id, removed_id, predecessor_id, role="prev"
                )
            else:
                # 头节点被删：后继 -> None (箭头应淡出)
                # 这就是导致崩溃的关键点：不要让它走 transition 逻辑，直接淡出
                arrow = self.arrow_items.get((successor_id, removed_id))
                if arrow:
                    extra_fade_arrows.append(arrow)
                    self.arrow_items.pop((successor_id, removed_id), None)

        # 3. 构建淡出动画组
        fade_group = self.anim.parallel()

        # 3.1 淡出被删除节点本身
        fade_group.addAnimation(self.anim.fade_item(target_node, 1.0, 0.0, duration=420))

        # 3.2 淡出从被删除节点出发的箭头 (removed -> next, removed -> prev)
        outgoing_anim = self._fade_outgoing_arrows(removed_id)
        if outgoing_anim:
            fade_group.addAnimation(outgoing_anim)

        # 3.3 淡出那些变成 None 的入边箭头 (例如 successor -> removed)
        for arrow in extra_fade_arrows:
            anim = QVariantAnimation()
            anim.setDuration(self.anim.global_ctrl.scale_duration(400))
            anim.setStartValue(1.0)
            anim.setEndValue(0.0)

            # 使用闭包捕获 arrow
            def _update_opacity(val, item=arrow):
                if item and item.scene():
                    item.setOpacity(val)

            def _remove_item(item=arrow):
                if item and item.scene():
                    item.scene().removeItem(item)

            anim.valueChanged.connect(_update_opacity)
            anim.finished.connect(_remove_item)
            fade_group.addAnimation(anim)

        # --- 组装动画序列 ---

        seq = self.anim.sequential(
            traversal,
            flash,
            self.anim.parallel(
                forward_transition if forward_transition else self.anim.pause(10),
                backward_transition if backward_transition else self.anim.pause(10),
            ),
            fade_group,
            self.anim.pause(100),
        )

        def _finalizer():
            self._finalize_delete(nodes, removed_id)
            for cb in (forward_restore, backward_restore):
                if cb:
                    cb()

        self._track_animation(seq, finalizer=_finalizer)

    def update_values(self, nodes):
        self.order = [node["id"] for node in nodes]
        changed_items = []

        for info in nodes:
            node_item = self.node_items.get(info["id"])
            if not node_item:
                continue
            new_value = str(info["value"])
            if node_item.value() != new_value:
                node_item.set_value(new_value)
                changed_items.append(node_item)

        if not changed_items:
            self._refresh_connectivity()
            return

        flashes = [
            self.anim.flash_brush(
                setter=item.setFillColor,
                start_color=item.fillColor,
                end_color=QColor("#4dd0e1"),
                duration=340,
                loops=2,
            )
            for item in changed_items
        ]
        group = self.anim.parallel(*flashes)
        self._track_animation(group, finalizer=self._refresh_connectivity)

    # ------------------------------------------------------------------ Helpers (state)

    def index_of(self, node_id):
        return self.order.index(node_id) if node_id in self.order else -1

    def _finalize_insert(self, nodes, new_node, index):
        self.order = [node["id"] for node in nodes]
        self.node_items[new_node.node_id] = new_node
        self._refresh_connectivity()

    def _finalize_delete(self, nodes, removed_id):
        # 1. 强制清理与该节点相关的所有箭头引用
        # 这一步至关重要：显式查找所有连接到 removed_id 的箭头并移除
        keys_to_remove = []
        for (start, end), arrow in self.arrow_items.items():
            if start == removed_id or end == removed_id:
                if arrow.scene():
                    self.scene.removeItem(arrow)
                keys_to_remove.append((start, end))

        for k in keys_to_remove:
            del self.arrow_items[k]

        # 2. 从字典中移除节点项并从场景移除
        node = self.node_items.pop(removed_id, None)
        if node and node.scene():
            self.scene.removeItem(node)

        # 3. 更新顺序并刷新
        self.order = [node["id"] for node in nodes]
        self._refresh_connectivity()

    def _wire_node(self, node_item):
        node_item.positionChanged.connect(self._update_arrows)
        node_item.positionChanged.connect(self._update_head_label)
        node_item.positionChanged.connect(self._update_head_tail_markers)
        node_item.contextDelete.connect(self._emit_delete)
        node_item.contextEdit.connect(self._emit_edit)
        node_item.dragStateChanged.connect(self._on_drag_state_changed)

    # ------------------------------------------------------------------ Arrow management

    def _rebuild_arrows(self):
        self._clear_arrows()
        if len(self.order) < 2:
            return

        for idx in range(len(self.order) - 1):
            left_id = self.order[idx]
            right_id = self.order[idx + 1]
            left_item = self.node_items.get(left_id)
            right_item = self.node_items.get(right_id)
            if not left_item or not right_item:
                continue

            forward = ArrowItem(left_item, right_item, role="next")
            backward = ArrowItem(right_item, left_item, role="prev")

            self.scene.addItem(forward)
            self.scene.addItem(backward)

            self.arrow_items[(left_id, right_id)] = forward
            self.arrow_items[(right_id, left_id)] = backward

    def _clear_arrows(self):
        for arrow in list(self.arrow_items.values()):
            self.scene.removeItem(arrow)
        self.arrow_items.clear()

    def _update_arrows(self, *_):
        self._refresh_arrow_paths()

    def _refresh_arrow_paths(self):
        for arrow in list(self.arrow_items.values()):
            arrow.update_path()

    def _build_arrow_transition(self, start_id, old_end_id, new_end_id, role):
        if start_id is None:
            return self.anim.pause(60), None

        arrow = None
        if old_end_id is not None:
            arrow = self.arrow_items.get((start_id, old_end_id))

        if arrow is None:
            start_item = self.node_items.get(start_id)
            if not start_item or new_end_id is None:
                return self.anim.pause(80), None
            anim = self._animate_new_arrow_link(
                start_item, new_end_id, role=role, duration=520
            )
            return anim if anim else self.anim.pause(80), None

        holder = {"arrow": arrow}
        current_pen = QPen(arrow.pen())
        start_color = QColor(current_pen.color())
        start_width = float(current_pen.widthF())

        highlight_color = QColor("#ff1744")
        highlight_width = max(5.0, start_width + 1.4)

        default_color = arrow.default_pen_color()
        default_width = arrow.default_pen_width()

        seq = self.anim.sequential()
        seq.addAnimation(self.anim.pause(40))
        seq.addAnimation(
            self._animate_arrow_style(
                arrow_ref=lambda: holder.get("arrow"),
                start_color=start_color,
                end_color=highlight_color,
                start_width=start_width,
                end_width=highlight_width,
                duration=360,
            )
        )
        seq.addAnimation(self.anim.pause(140))

        if new_end_id is None:
            fade = self.anim.fade_item(holder["arrow"], 1.0, 0.0, duration=340)

            def _cleanup():
                arrow_obj = holder.get("arrow")
                if arrow_obj:
                    self.scene.removeItem(arrow_obj)
                    self.arrow_items.pop((start_id, old_end_id), None)

            fade.finished.connect(_cleanup)
            seq.addAnimation(fade)
            return seq, None

        retarget = self._animate_arrow_retarget(
            holder=holder,
            start_id=start_id,
            old_end_id=old_end_id,
            new_end_id=new_end_id,
            role=role,
            duration=720,
        )
        if retarget:
            seq.addAnimation(retarget)
        else:
            seq.addAnimation(self.anim.pause(120))

        seq.addAnimation(self.anim.pause(100))

        def _restore_style():
            arrow_obj = holder.get("arrow")
            if arrow_obj is None or arrow_obj.scene() is None:
                return
            pen = QPen(arrow_obj.pen())
            pen.setColor(default_color)
            pen.setWidthF(default_width)
            arrow_obj.setPen(pen)

        return seq, _restore_style

    def _animate_arrow_retarget(
        self,
        holder,
        start_id,
        old_end_id,
        new_end_id,
        role,
        duration=650,
    ):
        arrow = holder.get("arrow")
        if arrow is None:
            return None

        old_end_item = self.node_items.get(old_end_id)
        new_end_item = self.node_items.get(new_end_id)
        if old_end_item is None or new_end_item is None:
            return None

        if role == "next":
            start_point = old_end_item.mapToScene(old_end_item.pointer_prev_entry_point())
            end_point = new_end_item.mapToScene(new_end_item.pointer_prev_entry_point())
        else:
            start_point = old_end_item.mapToScene(old_end_item.pointer_next_entry_point())
            end_point = new_end_item.mapToScene(new_end_item.pointer_next_entry_point())

        anim = QVariantAnimation()
        anim.setDuration(self.anim.global_ctrl.scale_duration(duration))
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)

        def _update(progress):
            arrow_obj = holder.get("arrow")
            if arrow_obj is None or arrow_obj.scene() is None:
                return
            interp = QPointF(
                start_point.x() + (end_point.x() - start_point.x()) * progress,
                start_point.y() + (end_point.y() - start_point.y()) * progress,
            )
            arrow_obj.set_override_target(interp)

        def _finish():
            arrow_obj = holder.get("arrow")
            if arrow_obj is None or arrow_obj.scene() is None:
                return
            arrow_obj.set_override_target(None)
            new_arrow = self._redirect_arrow(start_id, old_end_id, new_end_id, role)
            if new_arrow:
                holder["arrow"] = new_arrow

        anim.valueChanged.connect(_update)
        anim.finished.connect(_finish)
        return anim

    def _redirect_arrow(self, start_id, old_end_id, new_end_id, role):
        arrow = self.arrow_items.pop((start_id, old_end_id), None)
        if not arrow:
            return None
        if new_end_id is None or new_end_id not in self.node_items:
            if arrow.scene():
                arrow.scene().removeItem(arrow)
            return None

        new_end_item = self.node_items[new_end_id]
        arrow.rebind(end_item=new_end_item)
        arrow.set_pointer_role(role)
        arrow.update_path()
        self.arrow_items[(start_id, new_end_id)] = arrow
        return arrow

    def _animate_new_arrow_link(self, start_item, end_id, role, duration=700):
        if start_item is None or end_id is None:
            return None
        end_item = self.node_items.get(end_id)
        if end_item is None:
            return None

        arrow = ArrowItem(start_item, end_item, role=role)
        arrow.setOpacity(0.0)
        hover_target = self._compute_hover_target(start_item, role)
        arrow.set_override_target(hover_target)
        self.scene.addItem(arrow)
        arrow.update()
        arrow.setOpacity(1.0)
        self.arrow_items[(start_item.node_id, end_id)] = arrow

        final_target = self._entry_point_for_role(end_item, role)

        anim = QVariantAnimation()
        anim.setDuration(self.anim.global_ctrl.scale_duration(duration))
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)

        def _update(progress):
            if arrow.scene() is None:
                return
            interp = QPointF(
                hover_target.x() + (final_target.x() - hover_target.x()) * progress,
                hover_target.y() + (final_target.y() - hover_target.y()) * progress,
            )
            arrow.set_override_target(interp)

        def _finish():
            if arrow.scene() is None:
                return
            arrow.set_override_target(None)

        anim.valueChanged.connect(_update)
        anim.finished.connect(_finish)
        return anim

    def _compute_hover_target(self, node_item, role):
        anchor = node_item.mapToScene(
            node_item.pointer_next_center() if role == "next" else node_item.pointer_prev_center()
        )
        offset = node_item.pointer_size * 0.55
        if role == "next":
            return QPointF(anchor.x() + offset, anchor.y() - offset * 0.4)
        return QPointF(anchor.x() - offset, anchor.y() + offset * 0.4)

    def _entry_point_for_role(self, node_item, role):
        if role == "next":
            return node_item.mapToScene(node_item.pointer_prev_entry_point())
        return node_item.mapToScene(node_item.pointer_next_entry_point())

    def _fade_outgoing_arrows(self, node_id, duration=400):
        targets = [key for key in list(self.arrow_items.keys()) if key[0] == node_id]
        if not targets:
            return None

        group = self.anim.parallel()
        scaled = self.anim.global_ctrl.scale_duration(duration)

        for start_id, end_id in targets:
            arrow = self.arrow_items.pop((start_id, end_id), None)
            if not arrow:
                continue

            anim = QVariantAnimation()
            anim.setDuration(scaled)
            anim.setStartValue(1.0)
            anim.setEndValue(0.0)

            def _update_opacity(value, item=arrow):
                if item and item.scene():
                    item.setOpacity(float(value))

            def _remove(item=arrow):
                if item and item.scene():
                    item.scene().removeItem(item)

            anim.valueChanged.connect(_update_opacity)
            anim.finished.connect(_remove)
            group.addAnimation(anim)

        return group

    # ------------------------------------------------------------------ Visual helpers

    def _build_traversal_anim(self, index: int):
        if index < 0:
            return self.anim.pause(40)

        seq = self.anim.sequential()
        limit = min(index + 1, len(self.order))
        for i in range(limit):
            node_id = self.order[i]
            node_item = self.node_items.get(node_id)
            if not node_item:
                continue

            original_color = QColor(node_item.fillColor)
            flash = self.anim.flash_brush(
                setter=node_item.setFillColor,
                start_color=original_color,
                end_color=QColor("#64b5f6"),
                duration=360,
                loops=1,
            )

            def _restore(color=original_color, item=node_item):
                item.setFillColor(color)

            flash.finished.connect(_restore)
            seq.addAnimation(flash)

        return seq

    def _refresh_connectivity(self):
        self._rebuild_arrows()
        self._update_head_label()
        self._update_head_tail_markers()
        self._auto_scale_view()

    def _update_head_label(self):
        if not hasattr(self, "_head_label"):
            return

        if self._head_label.scene() is None:
            self.scene.addItem(self._head_label)

        if not self.order:
            self._head_label.setVisible(False)
            return

        head_id = self.order[0]
        head_item = self.node_items.get(head_id)
        if head_item is None or head_item.scene() is None:
            self._head_label.setVisible(False)
            return

        top_center = head_item.mapToScene(
            QPointF(head_item.total_width() / 2.0, 0.0)
        )
        rect = self._head_label.boundingRect()
        self._head_label.setPos(
            top_center.x() - rect.width() / 2.0,
            top_center.y() - rect.height() - 12,
        )
        self._head_label.setVisible(True)

    def _update_head_tail_markers(self):
        head_id = self.order[0] if self.order else None
        tail_id = self.order[-1] if self.order else None
        for node_id, item in self.node_items.items():
            item.set_head(node_id == head_id)
            item.set_tail(node_id == tail_id)

    def _auto_scale_view(self, padding=140):
        self.auto_fit_view(padding=padding, skip_if=lambda: self._dragging)

    def _estimate_target_x_position(self, index, centers):
        if not self.order:
            return 0.0
        index = max(0, min(index, len(self.order)))
        spacing = DoublyLinkedListNodeItem.min_total_width + 60

        if index == 0:
            first_center = centers.get(self.order[0])
            return first_center.x() - spacing if first_center else 0.0
        if index >= len(self.order):
            last_center = centers.get(self.order[-1])
            return last_center.x() + spacing if last_center else 0.0

        prev_center = centers.get(self.order[index - 1])
        next_center = centers.get(self.order[index])
        if prev_center and next_center:
            return (prev_center.x() + next_center.x()) / 2.0
        if prev_center:
            return prev_center.x() + spacing
        if next_center:
            return next_center.x() - spacing
        return 0.0

    def _pick_sparse_position(
        self,
        index=None,
        samples=28,
        margin_x=240,
        margin_y=220,
        neighbor_radius=200,
    ):
        if not self.node_items:
            return QPointF(0, 0)

        centers = self._compute_node_centers()
        xs = [pt.x() for pt in centers.values()]
        ys = [pt.y() for pt in centers.values()]

        min_x, max_x = min(xs), max(xs)
        baseline_y = sum(ys) / len(ys) if ys else 0.0
        preferred_x = (
            self._estimate_target_x_position(index, centers)
            if index is not None
            else (min_x + max_x) / 2.0
        )

        x_low = min_x - margin_x
        x_high = max_x + margin_x
        y_low = baseline_y - margin_y
        y_high = baseline_y + margin_y

        width_span = max(x_high - x_low, DoublyLinkedListNodeItem.min_total_width * 4)
        height_span = max(y_high - y_low, DoublyLinkedListNodeItem.height * 4)

        radius_sq = neighbor_radius ** 2
        best_candidate = None
        best_score = None

        for attempt in range(samples):
            if attempt % 4 == 0:
                cand_x = random.uniform(x_low, x_high)
                cand_y = random.uniform(y_low, y_high)
            elif attempt % 4 == 1:
                cand_x = random.gauss(preferred_x, width_span * 0.28)
                cand_y = random.gauss(baseline_y, height_span * 0.35)
            else:
                radius = random.uniform(0, max(width_span, height_span) * 0.45)
                theta = random.uniform(0.0, math.tau)
                cand_x = preferred_x + radius * math.cos(theta)
                cand_y = baseline_y + radius * math.sin(theta)

            cand_x = min(max(cand_x, x_low), x_high)
            cand_y = min(max(cand_y, y_low), y_high)
            cand = QPointF(cand_x, cand_y)

            min_dist_sq = float("inf")
            neighbor_count = 0
            for pt in centers.values():
                dx = cand.x() - pt.x()
                dy = cand.y() - pt.y()
                dist_sq = dx * dx + dy * dy
                if dist_sq < min_dist_sq:
                    min_dist_sq = dist_sq
                if dist_sq <= radius_sq:
                    neighbor_count += 1

            spread_bonus = (
                abs(cand_y - baseline_y)
                + 0.4 * abs(cand_x - preferred_x)
                + random.random() * 0.1
            )
            score = (-neighbor_count, min_dist_sq, spread_bonus)
            if best_score is None or score > best_score:
                best_score = score
                best_candidate = cand

        if best_candidate is None:
            best_candidate = QPointF(preferred_x, baseline_y)

        return best_candidate

    def _compute_node_centers(self):
        centers = {}
        for node_id, node_item in self.node_items.items():
            centers[node_id] = node_item.mapToScene(
                QPointF(node_item.total_width() / 2.0, node_item.height / 2.0)
            )
        return centers

    def _create_head_label(self):
        label = QGraphicsSimpleTextItem("HEAD")
        label.setBrush(QColor("#ff6b3b"))
        font = label.font()
        font.setBold(True)
        label.setFont(font)
        label.setZValue(50)
        label.setVisible(False)
        return label

    # ------------------------------------------------------------------ Context menu / events

    def _show_background_menu(self, screen_pos):
        if isinstance(screen_pos, QPointF):
            screen_pos = screen_pos.toPoint()

        menu = QMenu()
        clear_action = menu.addAction("Clear All")
        chosen = menu.exec_(screen_pos)
        if chosen == clear_action:
            self.clearAllRequested.emit()

    def eventFilter(self, watched, event):
        if watched is self.scene and event.type() == QEvent.GraphicsSceneContextMenu:
            item = self.scene.itemAt(event.scenePos(), self._canvas.transform() if self._canvas else None)
            if item is None:
                self._show_background_menu(event.screenPos())
                event.accept()
                return True
        return super().eventFilter(watched, event)

    # ------------------------------------------------------------------ Signals to controller

    def _emit_delete(self, node_id):
        idx = self.index_of(node_id)
        if idx != -1:
            self.deleteRequested.emit(idx)

    def _emit_edit(self, node_id):
        idx = self.index_of(node_id)
        if idx != -1:
            self.editRequested.emit(idx)

    def _on_drag_state_changed(self, dragging):
        self._dragging = dragging
        if dragging:
            self.lock_interactions()
        else:
            if not self._running:
                self.unlock_interactions()
            self._auto_scale_view()

    # ------------------------------------------------------------------ Shared animation helpers

    def _animate_arrow_style(
        self,
        arrow_ref,
        start_color,
        end_color,
        start_width,
        end_width,
        duration=280,
    ):
        anim = QVariantAnimation()
        anim.setDuration(self.anim.global_ctrl.scale_duration(duration))
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)

        start_color = QColor(start_color)
        end_color = QColor(end_color)
        start_width = float(start_width)
        end_width = float(end_width)

        start_rgba = start_color.getRgbF()
        end_rgba = end_color.getRgbF()

        def _update(progress):
            arrow = arrow_ref()
            if arrow is None or arrow.scene() is None:
                return

            r = start_rgba[0] + (end_rgba[0] - start_rgba[0]) * progress
            g = start_rgba[1] + (end_rgba[1] - start_rgba[1]) * progress
            b = start_rgba[2] + (end_rgba[2] - start_rgba[2]) * progress
            a = start_rgba[3] + (end_rgba[3] - start_rgba[3]) * progress

            pen = QPen(arrow.pen())
            pen.setColor(QColor.fromRgbF(r, g, b, a))
            pen.setWidthF(start_width + (end_width - start_width) * progress)
            arrow.setPen(pen)

        anim.valueChanged.connect(_update)
        return anim


class DoublyLinkedListNodeItem(QGraphicsObject):
    positionChanged = pyqtSignal()
    contextDelete = pyqtSignal(int)
    contextEdit = pyqtSignal(int)
    dragStateChanged = pyqtSignal(bool)

    height = 56
    pointer_size = 46
    data_base_width = 110
    min_total_width = data_base_width + pointer_size * 2

    def __init__(self, node_id, value):
        super().__init__()
        self.node_id = node_id
        self._value = str(value)

        self.fillColor = QColor("#cfd8dc")
        self.strokeColor = QColor("#37474f")
        self.textColor = QColor("#102027")
        self.pointerFill = QColor("#eceff1")
        self.pointerTextColor = QColor("#455a64")

        self.data_width = self.data_base_width
        self._label_font = self._create_label_font()
        self._is_head = False
        self._is_tail = False

        self.setFlags(
            QGraphicsItem.ItemIsMovable
            | QGraphicsItem.ItemIsSelectable
            | QGraphicsItem.ItemSendsGeometryChanges
        )

        self._adjust_data_width()

    # ---------------------- Geometry helpers

    def total_width(self):
        return self.pointer_size * 2 + self.data_width

    def boundingRect(self):
        return QRectF(0, 0, self.total_width(), self.height)

    def prev_rect(self):
        return QRectF(0, 0, self.pointer_size, self.height)

    def data_rect(self):
        return QRectF(self.pointer_size, 0, self.data_width, self.height)

    def next_rect(self):
        return QRectF(
            self.pointer_size + self.data_width,
            0,
            self.pointer_size,
            self.height,
        )

    def pointer_prev_center(self):
        return QPointF(self.pointer_size / 2.0, self.height / 2.0)

    def pointer_next_center(self):
        return QPointF(
            self.pointer_size + self.data_width + self.pointer_size / 2.0,
            self.height / 2.0,
        )

    def pointer_prev_entry_point(self):
        return QPointF(self.pointer_size * 0.25, self.height / 2.0)

    def pointer_next_entry_point(self):
        right_start = self.pointer_size + self.data_width
        return QPointF(
            right_start + self.pointer_size * 0.75,
            self.height / 2.0,
        )

    # ---------------------- Painting

    def paint(self, painter, option, widget=None):
        painter.setRenderHint(painter.Antialiasing)

        prev_rect = self.prev_rect()
        data_rect = self.data_rect()
        next_rect = self.next_rect()
        outer_rect = self.boundingRect()

        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(self.pointerFill))
        painter.drawRect(prev_rect)
        painter.drawRect(next_rect)

        painter.setBrush(QBrush(self.fillColor))
        painter.drawRect(data_rect)

        painter.setPen(QPen(self.strokeColor, 2.2))
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(outer_rect)
        painter.drawLine(
            QPointF(self.pointer_size, 1.0),
            QPointF(self.pointer_size, self.height - 1.0),
        )
        painter.drawLine(
            QPointF(self.pointer_size + self.data_width, 1.0),
            QPointF(self.pointer_size + self.data_width, self.height - 1.0),
        )

        painter.setFont(self._label_font)
        painter.setPen(self.textColor)
        text_rect = data_rect.adjusted(10, 0, -10, 0)
        painter.drawText(text_rect, Qt.AlignCenter, self._value)

        pointer_font = QFont(self._label_font)
        pointer_font.setPointSize(6)
        pointer_font.setBold(True)
        painter.setFont(pointer_font)
        painter.setPen(self.pointerTextColor)

        prev_text = "NULL" if self._is_head else "PREV"
        next_text = "NULL" if self._is_tail else "NEXT"

        painter.drawText(prev_rect.adjusted(4, 0, -4, 0), Qt.AlignCenter, prev_text)
        painter.drawText(next_rect.adjusted(4, 0, -4, 0), Qt.AlignCenter, next_text)

    # ---------------------- Public API

    def value(self):
        return self._value

    def set_value(self, value: str):
        self._value = str(value)
        self._adjust_data_width()
        self.update()

    def setFillColor(self, color: QColor):
        self.fillColor = QColor(color)
        self.update()

    def set_head(self, is_head: bool):
        if self._is_head != is_head:
            self._is_head = is_head
            self.update()

    def set_tail(self, is_tail: bool):
        if self._is_tail != is_tail:
            self._is_tail = is_tail
            self.update()

    # ---------------------- Events / signals

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionChange:
            self.positionChanged.emit()
        return super().itemChange(change, value)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.dragStateChanged.emit(True)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        self.dragStateChanged.emit(False)

    def contextMenuEvent(self, event):
        menu = QMenu()
        delete_action = menu.addAction("Delete")
        edit_action = menu.addAction("Edit Value")
        chosen = menu.exec_(event.screenPos())
        if chosen == delete_action:
            self.contextDelete.emit(self.node_id)
        elif chosen == edit_action:
            self.contextEdit.emit(self.node_id)

    # ---------------------- Internals

    def _create_label_font(self):
        font = QFont()
        font.setPointSize(14)
        font.setBold(True)
        return font

    def _adjust_data_width(self):
        metrics = QFontMetrics(self._label_font)
        padding = 36
        required = metrics.horizontalAdvance(self._value) + padding
        new_width = max(self.data_base_width, required)
        if new_width != self.data_width:
            self.prepareGeometryChange()
            self.data_width = new_width


class ArrowItem(QGraphicsPathItem):
    def __init__(
        self,
        start_item: DoublyLinkedListNodeItem,
        end_item: DoublyLinkedListNodeItem,
        role: str = "next",
    ):
        super().__init__()
        self.start_item = start_item
        self.end_item = end_item
        self.pointer_role = role
        self._override_target: Optional[QPointF] = None
        self._arrow_head_path = QPainterPath()

        pen = QPen(QColor("#ff8c00"), 3)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        self._default_pen = QPen(pen)
        self.setPen(QPen(self._default_pen))
        self.setZValue(5)

        self.update_path()

    def set_pointer_role(self, role: str):
        self.pointer_role = "next" if role == "next" else "prev"
        self.update_path()

    def set_override_target(self, point: Optional[QPointF]):
        self._override_target = QPointF(point) if point is not None else None
        self.update_path()

    def default_pen_color(self):
        return QColor(self._default_pen.color())

    def default_pen_width(self):
        return self._default_pen.widthF()

    def rebind(self, start_item=None, end_item=None):
        if start_item is not None:
            self.start_item = start_item
        if end_item is not None:
            self.end_item = end_item
        self.update_path()

    def update_path(self):
        if self.start_item is None or self.end_item is None:
            return

        start_anchor = self.start_item.mapToScene(
            self.start_item.pointer_next_center()
            if self.pointer_role == "next"
            else self.start_item.pointer_prev_center()
        )

        if self._override_target is not None:
            target_center = self._override_target
        else:
            target_center = (
                self.end_item.mapToScene(self.end_item.pointer_prev_entry_point())
                if self.pointer_role == "next"
                else self.end_item.mapToScene(self.end_item.pointer_next_entry_point())
            )

        dx = target_center.x() - start_anchor.x()
        dy = target_center.y() - start_anchor.y()
        distance = math.hypot(dx, dy)
        if distance < 1e-3:
            distance = 1.0

        entry_gap = max(20.0, self.end_item.pointer_size * 0.35)
        if distance <= entry_gap + 4.0:
            entry_gap = max(distance * 0.4, 6.0)

        norm_dx = dx / distance
        norm_dy = dy / distance

        end_point = QPointF(
            target_center.x() - norm_dx * entry_gap,
            target_center.y() - norm_dy * entry_gap,
        )

        horizontal = max(1.0, abs(end_point.x() - start_anchor.x()))
        arc_height = max(30.0, min(120.0, horizontal * 0.35))
        mid_y = (start_anchor.y() + end_point.y()) / 2.0

        ctrl_y = mid_y - arc_height if self.pointer_role == "next" else mid_y + arc_height
        ctrl = QPointF((start_anchor.x() + end_point.x()) / 2.0, ctrl_y)

        path = QPainterPath(start_anchor)
        path.quadTo(ctrl, end_point)

        self.setPath(path)
        self._arrow_head_path = self._build_arrow_head(path)

    def _build_arrow_head(self, path: QPainterPath) -> QPainterPath:
        length = 28
        angle_deg = 26
        end_point = path.pointAtPercent(1.0)
        tangent = path.angleAtPercent(1.0)

        angle1 = math.radians(tangent + 180 - angle_deg)
        angle2 = math.radians(tangent + 180 + angle_deg)

        p1 = QPointF(
            end_point.x() + length * math.cos(angle1),
            end_point.y() - length * math.sin(angle1),
        )
        p2 = QPointF(
            end_point.x() + length * math.cos(angle2),
            end_point.y() - length * math.sin(angle2),
        )

        arrow = QPainterPath()
        arrow.moveTo(end_point)
        arrow.lineTo(p1)
        arrow.moveTo(end_point)
        arrow.lineTo(p2)
        return arrow

    def paint(self, painter, option, widget=None):
        painter.setRenderHint(painter.Antialiasing, True)
        painter.setPen(self.pen())
        painter.drawPath(self.path())
        painter.drawPath(self._arrow_head_path)


class DoublyLinkedListViewWithPersistence(DoublyLinkedListView):
    saveRequested = pyqtSignal()
    loadRequested = pyqtSignal()
    saveImageRequested = pyqtSignal()  # [新增] 定义保存图片的信号

    def _show_background_menu(self, screen_pos):
        if isinstance(screen_pos, QPointF):
            screen_pos = screen_pos.toPoint()

        menu = QMenu()
        open_action = menu.addAction("Open From File…")
        save_action = menu.addAction("Save To File…")
        save_img_action = menu.addAction("Save as Image…")  # [新增] 菜单项
        menu.addSeparator()
        clear_action = menu.addAction("Clear All")

        chosen = menu.exec_(screen_pos)
        if chosen == open_action:
            self.loadRequested.emit()
        elif chosen == save_action:
            self.saveRequested.emit()
        elif chosen == save_img_action:
            self.saveImageRequested.emit()  # [新增] 触发信号
        elif chosen == clear_action:
            self.clearAllRequested.emit()