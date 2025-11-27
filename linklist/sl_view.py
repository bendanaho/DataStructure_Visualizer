import math, random
from PyQt5.QtCore import (
    QPointF,
    Qt,
    pyqtSignal,
    QVariantAnimation,
    QRectF,
    QEvent,
)
from PyQt5.QtGui import QColor, QBrush, QPainterPath, QPen, QTransform
from PyQt5.QtWidgets import (
    QGraphicsItem,
    QGraphicsObject,
    QGraphicsPathItem,
    QMenu,
    QGraphicsSimpleTextItem,
)

from core.base_view import BaseStructureView


class LinkedListView(BaseStructureView):
    deleteRequested = pyqtSignal(int)
    editRequested = pyqtSignal(int)
    clearAllRequested = pyqtSignal()

    def __init__(self, global_ctrl):
        super().__init__(global_ctrl)
        self.scene.installEventFilter(self)

        self.node_items = {}  # id -> LinkedListNodeItem
        self.order = []  # list of node ids in order
        self._dragging = False
        self.arrow_items = {}  # (start_id, end_id) -> ArrowItem
        self._default_scene_rect = QRectF(self.scene.sceneRect())
        self._scaled = False

        self._head_label = self._create_head_label()
        self.scene.addItem(self._head_label)

    # ---------- Scene lifecycle ----------

    def reset(self):
        self.scene.clear()
        self.node_items.clear()
        self.order.clear()
        self.arrow_items.clear()

        self._head_label = self._create_head_label()
        self.scene.addItem(self._head_label)

    def animate_build(self, nodes):
        """
        nodes: ordered list of dicts {id, value}
        """
        self.reset()

        sequential = self.anim.sequential()

        for idx, info in enumerate(nodes):
            target_position = self._pick_sparse_position(index=idx)
            node_item = LinkedListNodeItem(info["id"], info["value"])
            node_item.setOpacity(0.0)
            start_pos = QPointF(target_position.x(), target_position.y() - 120)
            node_item.setPos(start_pos)
            node_item.positionChanged.connect(self._update_arrows)
            node_item.positionChanged.connect(self._update_head_label)
            node_item.contextDelete.connect(self._emit_delete)
            node_item.contextEdit.connect(self._emit_edit)
            node_item.dragStateChanged.connect(self._on_drag_state_changed)

            self.scene.addItem(node_item)
            self.node_items[info["id"]] = node_item
            self.order.append(info["id"])

            fade = self.anim.fade_item(node_item, 0, 1, duration=600)
            drop = self.anim.move_item(node_item, target_position, duration=800)
            sequential.addAnimation(self.anim.parallel(fade, drop))

        self._auto_scale_view()
        sequential.addAnimation(self.anim.pause(150))
        self._track_animation(sequential, finalizer=self._refresh_connectivity)

    def animate_insert(self, nodes, inserted_id, index):
        new_info = next(node for node in nodes if node["id"] == inserted_id)
        target_position = self._pick_sparse_position(index=index)

        new_node = LinkedListNodeItem(new_info["id"], new_info["value"])
        new_node.setOpacity(0.0)
        new_node.setPos(QPointF(target_position.x(), target_position.y() - 120))
        new_node.positionChanged.connect(self._update_arrows)
        new_node.positionChanged.connect(self._update_head_label)
        new_node.contextDelete.connect(self._emit_delete)
        new_node.contextEdit.connect(self._emit_edit)
        new_node.dragStateChanged.connect(self._on_drag_state_changed)
        self.scene.addItem(new_node)
        self.node_items[new_node.node_id] = new_node
        self._auto_scale_view()

        predecessor_id = self.order[index - 1] if index > 0 else None
        successor_id = self.order[index] if index < len(self.order) else None

        traversal = self._build_traversal_anim(index)

        fade_in = self.anim.parallel(
            self.anim.move_item(new_node, target_position, duration=650),
            self.anim.fade_item(new_node, 0.0, 1.0, duration=650),
        )

        flash_new = self.anim.flash_brush(
            setter=new_node.setFillColor,
            start_color=new_node.fillColor,
            end_color=QColor("#ff4d4d"),
            duration=450,
            loops=2,
        )

        forward_arrow_anim = self._animate_new_arrow_link(new_node, successor_id)
        if forward_arrow_anim is None:
            forward_arrow_anim = self.anim.pause(100)

        arrow_transition, arrow_restore = self._build_arrow_transition(
            predecessor_id, successor_id, new_node.node_id
        )
        predecessor_anim = arrow_transition if arrow_transition else self.anim.pause(80)

        combined = self.anim.sequential(
            traversal,
            fade_in,
            flash_new,
            forward_arrow_anim,
            predecessor_anim,
        )

        def _finalizer():
            self._finalize_insert(nodes, new_node, index)
            if arrow_restore:
                arrow_restore()

        self._track_animation(combined, finalizer=_finalizer)

    def animate_delete(self, nodes, removed_id, index):
        target_node = self.node_items.get(removed_id)
        if not target_node:
            return

        traversal = self._build_traversal_anim(max(0, index - 1))
        predecessor_id = self.order[index - 1] if index > 0 else None
        successor_id = self.order[index + 1] if index + 1 < len(self.order) else None

        flash = self.anim.flash_brush(
            setter=target_node.setFillColor,
            start_color=target_node.fillColor,
            end_color=QColor("#ff4d4d"),
            duration=450,
            loops=2,
        )

        arrow_transition, arrow_restore = self._build_arrow_transition(
            predecessor_id, removed_id, successor_id
        )

        outgoing_arrow_fade = self._fade_outgoing_arrows(removed_id)
        fade_out_node = self.anim.fade_item(target_node, 1.0, 0.0, duration=400)
        fade_phase = (
            self.anim.parallel(fade_out_node, outgoing_arrow_fade)
            if outgoing_arrow_fade
            else fade_out_node
        )

        seq = self.anim.sequential(
            traversal,
            flash,
            arrow_transition if arrow_transition else self.anim.pause(60),
            fade_phase,
            self.anim.pause(80),
        )

        def _finalizer():
            self._finalize_delete(nodes, removed_id)
            if arrow_restore:
                arrow_restore()

        self._track_animation(seq, finalizer=_finalizer)

    def update_values(self, nodes):
        """更新节点文字，如果值发生变化则触发闪烁提示。"""
        self.order = [node["id"] for node in nodes]
        changed_items = []

        for info in nodes:
            node_item = self.node_items.get(info["id"])
            if not node_item:
                continue

            new_value = str(info["value"])
            value_changed = node_item.value() != new_value
            node_item.set_value(new_value)

            if value_changed:
                changed_items.append(node_item)

        if not changed_items:
            self._refresh_connectivity()
            return

        flashes = [
            self.anim.flash_brush(
                setter=item.setFillColor,
                start_color=item.fillColor,
                end_color=QColor("#4dd0e1"),
                duration=360,
                loops=2,
            )
            for item in changed_items
        ]

        group = self.anim.parallel(*flashes)
        self._track_animation(group, finalizer=self._refresh_connectivity)

    # ---------- Helpers ----------

    def index_of(self, node_id):
        return self.order.index(node_id) if node_id in self.order else -1

    def _finalize_insert(self, nodes, new_node, index):
        self.order.insert(index, new_node.node_id)
        self.node_items[new_node.node_id] = new_node
        self.order = [node["id"] for node in nodes]
        self._refresh_connectivity()

    def _finalize_delete(self, nodes, removed_id):
        node = self.node_items.pop(removed_id, None)
        if node:
            self.scene.removeItem(node)
        self.order = [node["id"] for node in nodes]
        self._refresh_connectivity()

    def _rebuild_arrows(self):
        self._clear_arrows()

        if len(self.order) < 2:
            return

        centers = self._compute_node_centers()
        if len(centers) < 2:
            return

        classifications = self._classify_nodes_by_height(centers)

        for i in range(len(self.order) - 1):
            start_id = self.order[i]
            end_id = self.order[i + 1]
            if start_id not in self.node_items or end_id not in self.node_items:
                continue
            orientation = self._decide_arc_orientation(
                start_id, end_id, classifications, centers
            )
            arrow = ArrowItem(
                self.node_items[start_id],
                self.node_items[end_id],
                orientation=orientation,
            )
            self.scene.addItem(arrow)
            self.arrow_items[(start_id, end_id)] = arrow

    def _classify_nodes_by_height(self, centers):
        classifications = {}
        for idx, node_id in enumerate(self.order):
            if node_id not in centers:
                classifications[node_id] = None
                continue
            y = centers[node_id].y()
            prev_id = self.order[idx - 1] if idx > 0 else None
            next_id = self.order[idx + 1] if idx < len(self.order) - 1 else None
            prev_y = centers[prev_id].y() if prev_id and prev_id in centers else None
            next_y = centers[next_id].y() if next_id and next_id in centers else None

            if prev_y is None or next_y is None:
                classifications[node_id] = None
                continue

            if y > prev_y and y > next_y:
                classifications[node_id] = "valley"
            elif y < prev_y and y < next_y:
                classifications[node_id] = "peak"
            else:
                classifications[node_id] = None
        return classifications

    def _decide_arc_orientation(self, start_id, end_id, classifications, centers):
        if start_id not in centers or end_id not in centers:
            return "down"
        start_class = classifications.get(start_id)
        end_class = classifications.get(end_id)

        if start_class == "valley":
            return "down"
        if start_class == "peak":
            return "up"
        if end_class == "valley":
            return "down"
        if end_class == "peak":
            return "up"

        start_y = centers[start_id].y()
        end_y = centers[end_id].y()
        return "down" if start_y <= end_y else "up"

    def _update_arrows(self, *_):
        self._refresh_arrow_paths()

    def _refresh_arrow_paths(self):
        if not self.arrow_items:
            return

        centers = self._compute_node_centers()
        if not centers:
            return

        classifications = self._classify_nodes_by_height(centers)

        for (start_id, end_id), arrow in self.arrow_items.items():
            if start_id not in self.node_items or end_id not in self.node_items:
                continue
            orientation = self._decide_orientation_for_pair(
                start_id, end_id, classifications, centers
            )
            arrow.set_orientation(orientation)
            arrow.update_path()

    def _decide_orientation_for_pair(
        self, start_id, end_id, classifications, centers
    ):
        try:
            start_idx = self.order.index(start_id)
            if start_idx + 1 < len(self.order) and self.order[start_idx + 1] == end_id:
                return self._decide_arc_orientation(
                    start_id, end_id, classifications, centers
                )
        except ValueError:
            pass
        start_point = centers.get(start_id)
        end_point = centers.get(end_id)
        if not start_point or not end_point:
            return "down"
        return "down" if start_point.y() <= end_point.y() else "up"

    def _build_arrow_transition(self, predecessor_id, removed_id, successor_id):
        if predecessor_id is None:
            return self.anim.pause(60), None

        arrow = self.arrow_items.get((predecessor_id, removed_id))
        if arrow is None:
            return self.anim.pause(60), None

        holder = {"arrow": arrow}

        current_pen = QPen(arrow.pen())
        start_color = QColor(current_pen.color())
        start_width = float(current_pen.widthF())
        highlight_color = QColor("#ff1744")
        highlight_width = max(5.0, start_width + 1.5)

        default_color = arrow.default_pen_color()
        default_width = arrow.default_pen_width()

        seq = self.anim.sequential()

        # 与节点闪烁错开
        seq.addAnimation(self.anim.pause(40))

        # 逐渐加粗并标红
        seq.addAnimation(
            self._animate_arrow_style(
                arrow_ref=lambda: holder["arrow"],
                start_color=start_color,
                end_color=highlight_color,
                start_width=start_width,
                end_width=highlight_width,
                duration=360,
            )
        )

        # 高亮状态保持一段时间
        seq.addAnimation(self.anim.pause(160))

        # 慢速执行箭头指向更新动画
        retarget_anim = self._animate_arrow_retarget(
            holder=holder,
            predecessor_id=predecessor_id,
            removed_id=removed_id,
            successor_id=successor_id,
            duration=700,
        )
        if retarget_anim:
            seq.addAnimation(retarget_anim)
        else:
            seq.addAnimation(self.anim.pause(120))

        # 指向更新完成后再等待，确保节点删除在其后
        seq.addAnimation(self.anim.pause(180))

        # 维持高亮直到整体动画结束
        seq.addAnimation(self.anim.pause(80))

        def _restore_style():
            arrow_obj = holder.get("arrow")
            if arrow_obj is None or arrow_obj.scene() is None:
                return
            pen = QPen(arrow_obj.pen())
            pen.setColor(default_color)
            pen.setWidthF(default_width)
            arrow_obj.setPen(pen)

        return seq, _restore_style

    def _animate_new_arrow_link(self, start_node, successor_id, duration=700):
        if successor_id is None:
            return None

        successor_item = self.node_items.get(successor_id)
        if successor_item is None:
            return None

        start_center = start_node.mapToScene(
            QPointF(LinkedListNodeItem.width, LinkedListNodeItem.height / 2)
        )
        end_center = successor_item.mapToScene(
            QPointF(LinkedListNodeItem.width / 2, LinkedListNodeItem.height / 2)
        )

        hover_target = QPointF(
            start_center.x() + LinkedListNodeItem.width * 0.9,
            start_center.y(),
        )

        arrow = ArrowItem(start_node, successor_item, orientation="right")
        arrow.setOpacity(0.0)
        arrow.setZValue(-1)
        arrow.set_override_target(hover_target)
        self.scene.addItem(arrow)
        arrow.update()
        arrow.setOpacity(1.0)
        self.arrow_items[(start_node.node_id, successor_id)] = arrow

        anim = QVariantAnimation()
        anim.setDuration(self.anim.global_ctrl.scale_duration(duration))
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)

        def _update(progress):
            if arrow.scene() is None:
                return
            interp = QPointF(
                hover_target.x() + (end_center.x() - hover_target.x()) * progress,
                hover_target.y() + (end_center.y() - hover_target.y()) * progress,
            )
            arrow.set_override_target(interp)

        def _finish():
            if arrow.scene() is None:
                return
            arrow.set_override_target(None)

        anim.valueChanged.connect(_update)
        anim.finished.connect(_finish)
        return anim

    def _animate_arrow_retarget(
        self,
        holder,
        predecessor_id,
        removed_id,
        successor_id,
        duration=650,
    ):
        if successor_id is None:
            # 没有后继节点，不需要重新指向
            return None

        arrow = holder.get("arrow")
        if arrow is None:
            return None

        old_end_item = self.node_items.get(removed_id)
        new_end_item = self.node_items.get(successor_id)
        if old_end_item is None or new_end_item is None:
            return None

        start_point = old_end_item.mapToScene(
            QPointF(LinkedListNodeItem.width / 2, LinkedListNodeItem.height / 2)
        )
        end_point = new_end_item.mapToScene(
            QPointF(LinkedListNodeItem.width / 2, LinkedListNodeItem.height / 2)
        )

        centers = self._compute_node_centers()
        classifications = self._classify_nodes_by_height(centers)
        orientation = self._decide_orientation_for_pair(
            predecessor_id, successor_id, classifications, centers
        )
        arrow.set_orientation(orientation)

        anim = QVariantAnimation()
        anim.setDuration(self.anim.global_ctrl.scale_duration(duration))
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)

        def _update(progress):
            if arrow.scene() is None:
                return
            interp = QPointF(
                start_point.x() + (end_point.x() - start_point.x()) * progress,
                start_point.y() + (end_point.y() - start_point.y()) * progress,
            )
            arrow.set_override_target(interp)

        def _finish():
            if arrow.scene() is None:
                return
            arrow.set_override_target(None)
            new_arrow = self._redirect_arrow(
                predecessor_id, removed_id, successor_id
            )
            holder["arrow"] = new_arrow

        anim.valueChanged.connect(_update)
        anim.finished.connect(_finish)
        return anim

    def _redirect_arrow(self, start_id, old_end_id, new_end_id):
        arrow = self.arrow_items.pop((start_id, old_end_id), None)
        if not arrow:
            return None
        if new_end_id is None or new_end_id not in self.node_items:
            self.scene.removeItem(arrow)
            return None

        new_end_item = self.node_items[new_end_id]
        arrow.rebind(end_item=new_end_item)

        centers = self._compute_node_centers()
        classifications = self._classify_nodes_by_height(centers)
        orientation = self._decide_orientation_for_pair(
            start_id, new_end_id, classifications, centers
        )
        arrow.set_orientation(orientation)
        arrow.update_path()

        self.arrow_items[(start_id, new_end_id)] = arrow
        return arrow

    def _compute_node_centers(self):
        centers = {}
        for node_id, node_item in self.node_items.items():
            centers[node_id] = node_item.mapToScene(
                QPointF(LinkedListNodeItem.width / 2, LinkedListNodeItem.height / 2)
            )
        return centers

    def _clear_arrows(self):
        for arrow in list(self.arrow_items.values()):
            self.scene.removeItem(arrow)
        self.arrow_items.clear()

    def _build_traversal_anim(self, index):
        if index < 0:
            return self.anim.pause(50)
        seq = self.anim.sequential()
        for i in range(min(index + 1, len(self.order))):
            node_id = self.order[i]
            node_item = self.node_items[node_id]
            seq.addAnimation(
                self.anim.flash_brush(
                    setter=node_item.setStrokeColor,
                    start_color=node_item.strokeColor,
                    end_color=QColor("#4fc3f7"),
                    duration=250,
                    loops=1,
                )
            )
        return seq

    # ---------- Context menu on background ----------

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
            item = self.scene.itemAt(event.scenePos(), QTransform())
            if item is None:
                self._show_background_menu(event.screenPos())
                event.accept()
                return True
        return super().eventFilter(watched, event)

    # ---------- Signals ----------

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

    def _create_head_label(self):
        label = QGraphicsSimpleTextItem("head")
        label.setBrush(QColor("#ff6b3b"))
        font = label.font()
        font.setBold(True)
        label.setFont(font)
        label.setZValue(50)
        label.setVisible(False)
        return label

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

    def _fade_outgoing_arrows(self, node_id, duration=400):
        targets = [
            key for key in list(self.arrow_items.keys())
            if key[0] == node_id
        ]
        if not targets:
            return None

        group = self.anim.parallel()
        attached = False
        scaled_duration = self.anim.global_ctrl.scale_duration(duration)

        for start_id, end_id in targets:
            arrow = self.arrow_items.pop((start_id, end_id), None)
            if not arrow:
                continue

            anim = QVariantAnimation()
            anim.setDuration(scaled_duration)
            anim.setStartValue(1.0)
            anim.setEndValue(0.0)

            def _update_opacity(value, item=arrow):
                if item is None or item.scene() is None:
                    return
                item.setOpacity(float(value))

            anim.valueChanged.connect(_update_opacity)

            def _remove_arrow(item=arrow):
                if item and item.scene():
                    self.scene.removeItem(item)

            anim.finished.connect(_remove_arrow)

            group.addAnimation(anim)
            attached = True

        return group if attached else None

    def _pick_sparse_position(
        self,
        index=None,
        samples=28,
        margin_x=220,
        margin_y=200,
        neighbor_radius=180,
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

        width_span = max(x_high - x_low, LinkedListNodeItem.width * 5)
        height_span = max(y_high - y_low, LinkedListNodeItem.height * 4)

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

    def _refresh_connectivity(self):
        self._rebuild_arrows()
        self._auto_scale_view()
        self._update_head_label()

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
            QPointF(LinkedListNodeItem.width / 2, 0)
        )
        label_rect = self._head_label.boundingRect()
        self._head_label.setPos(
            top_center.x() - label_rect.width() / 2,
            top_center.y() - label_rect.height() - 12,
        )
        self._head_label.setVisible(True)

    def _auto_scale_view(self, padding=120):
        if not self._canvas or self._dragging:
            return

        items_rect = self.scene.itemsBoundingRect()
        if items_rect.isNull():
            return

        padded = QRectF(items_rect)
        padded.adjust(-padding, -padding, padding, padding)

        base = self._default_scene_rect

        if base.contains(padded):
            if self._scaled:
                self._canvas.resetTransform()
                self._scaled = False
            self.scene.setSceneRect(base)
            self._canvas.ensureVisible(items_rect, padding, padding)
            return

        target_rect = padded
        self.scene.setSceneRect(target_rect)

        self._canvas.resetTransform()
        viewport = self._canvas.viewport().rect()
        if viewport.isNull():
            return

        need_zoom_out = (
            target_rect.width() > viewport.width()
            or target_rect.height() > viewport.height()
        )

        if need_zoom_out:
            self._canvas.fitInView(target_rect, Qt.KeepAspectRatio)
            self._scaled = True
        else:
            self._canvas.centerOn(target_rect.center())
            self._scaled = False

    def _estimate_target_x_position(self, index, centers):
        if not self.order:
            return 0.0
        index = max(0, min(index, len(self.order)))
        spacing = LinkedListNodeItem.width + 40
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


class LinkedListNodeItem(QGraphicsObject):
    positionChanged = pyqtSignal()
    contextDelete = pyqtSignal(int)
    contextEdit = pyqtSignal(int)
    dragStateChanged = pyqtSignal(bool)

    width = 100
    height = 50

    def __init__(self, node_id, value):
        super().__init__()
        self.node_id = node_id
        self._value = str(value)
        self.fillColor = QColor("#2d9cdb")
        self.strokeColor = QColor("#102a43")
        self.setFlags(
            QGraphicsItem.ItemIsMovable
            | QGraphicsItem.ItemIsSelectable
            | QGraphicsItem.ItemSendsGeometryChanges
        )

    def boundingRect(self):
        return self._rect()

    def _rect(self):
        from PyQt5.QtCore import QRectF

        return QRectF(0, 0, self.width, self.height)

    def paint(self, painter, option, widget=None):
        painter.setRenderHint(painter.Antialiasing)
        painter.setPen(QPen(self.strokeColor, 2))
        painter.setBrush(QBrush(self.fillColor))
        painter.drawRoundedRect(self._rect(), 14, 14)

        font = painter.font()
        font.setPointSize(14)
        painter.setFont(font)
        painter.setPen(Qt.white)
        painter.drawText(self._rect(), Qt.AlignCenter, self._value)

    def value(self):
        return self._value

    def set_value(self, value: str):
        self._value = str(value)
        self.update()

    def setFillColor(self, color: QColor):
        self.fillColor = QColor(color)
        self.update()

    def setStrokeColor(self, color: QColor):
        self.strokeColor = QColor(color)
        self.update()

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


class ArrowItem(QGraphicsPathItem):
    def __init__(self, start_item: LinkedListNodeItem, end_item: LinkedListNodeItem, orientation="auto"):
        super().__init__()
        self.start_item = start_item
        self.end_item = end_item
        self.orientation = orientation
        self._arrow_head_path = QPainterPath()
        self._override_target = None  # 用于动画时临时覆盖目标点

        pen = QPen(QColor("#ff8c00"), 3)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        self._default_pen = QPen(pen)
        self.setPen(QPen(self._default_pen))
        self.setZValue(-1)

        self.update_path()

    def set_highlight(self, color="#ff1744", width=5):
        pen = QPen(self._default_pen)
        pen.setColor(QColor(color))
        pen.setWidthF(width)
        self.setPen(pen)

    def reset_style(self):
        self.setPen(QPen(self._default_pen))

    def default_pen_color(self):
        return QColor(self._default_pen.color())

    def default_pen_width(self):
        return self._default_pen.widthF()

    def set_orientation(self, orientation):
        if orientation not in {"up", "down", "auto"}:
            orientation = "auto"
        self.orientation = orientation

    def rebind(self, start_item=None, end_item=None):
        if start_item is not None:
            self.start_item = start_item
        if end_item is not None:
            self.end_item = end_item
        self.update_path()

    def set_override_target(self, point: QPointF = None):
        if point is None:
            self._override_target = None
        else:
            self._override_target = QPointF(point)
        self.update_path()

    def update_path(self):
        start_anchor = self.start_item.mapToScene(
            QPointF(LinkedListNodeItem.width, LinkedListNodeItem.height / 2)
        )

        if self._override_target is not None:
            target_center = self._override_target
        else:
            target_center = self.end_item.mapToScene(
                QPointF(LinkedListNodeItem.width / 2, LinkedListNodeItem.height / 2)
            )

        dx = target_center.x() - start_anchor.x()
        dy = target_center.y() - start_anchor.y()
        distance = max((dx ** 2 + dy ** 2) ** 0.5, 1.0)
        retreat = LinkedListNodeItem.width * 0.6

        if distance <= retreat + 8:
            retreat = max(distance * 0.4, 8.0)

        end_point = QPointF(
            target_center.x() - dx / distance * retreat,
            target_center.y() - dy / distance * retreat,
        )

        horizontal = max(1.0, abs(end_point.x() - start_anchor.x()))
        arc_height = max(30.0, min(90.0, horizontal * 0.32))
        mid_y = (start_anchor.y() + end_point.y()) / 2.0

        if self.orientation == "down":
            ctrl_y = mid_y + arc_height
        elif self.orientation == "up":
            ctrl_y = mid_y - arc_height
        else:
            ctrl_y = mid_y - arc_height if start_anchor.y() > end_point.y() else mid_y + arc_height

        ctrl = QPointF((start_anchor.x() + end_point.x()) / 2.0, ctrl_y)

        path = QPainterPath(start_anchor)
        path.quadTo(ctrl, end_point)

        self.setPath(path)
        self._arrow_head_path = self._build_arrow_head(path)

    def _build_arrow_head(self, path: QPainterPath) -> QPainterPath:
        length = 30  # 箭头大小
        angle_deg = 26
        end_point = path.pointAtPercent(1.0)
        tangent = path.angleAtPercent(1.0)

        from math import radians, cos, sin

        angle1 = radians(tangent + 180 - angle_deg)
        angle2 = radians(tangent + 180 + angle_deg)

        p1 = QPointF(
            end_point.x() + length * cos(angle1),
            end_point.y() - length * sin(angle1),
        )
        p2 = QPointF(
            end_point.x() + length * cos(angle2),
            end_point.y() - length * sin(angle2),
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