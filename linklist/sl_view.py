import math, random
from PyQt5.QtCore import (
    QPointF,
    Qt,
    pyqtSignal,
    QVariantAnimation,
    QRectF,
    QEvent,
    QTimer,
)
from PyQt5.QtGui import QColor, QBrush, QPainterPath, QPen, QTransform, QFont, QFontMetrics
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
        self.arrow_items = {}

        self._head_label = self._create_head_label()
        self.scene.addItem(self._head_label)

    # ---------- Scene lifecycle ----------
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
        # 1. 创建新节点图形项（初始状态：透明、在目标位置上方120px）
        new_info = next(node for node in nodes if node["id"] == inserted_id)
        target_position = self._pick_sparse_position(index=index)                   # 计算新节点的目标位置
        new_node = LinkedListNodeItem(new_info["id"], new_info["value"])
        new_node.setOpacity(0.0)
        new_node.setPos(QPointF(target_position.x(), target_position.y() - 120))    # 目标位置的上方120位置
        # 2. 注册事件监听
        new_node.positionChanged.connect(self._update_arrows)
        new_node.positionChanged.connect(self._update_head_label)                   # 拖动时更新箭头
        new_node.contextDelete.connect(self._emit_delete)                           # 右键删除
        new_node.contextEdit.connect(self._emit_edit)
        new_node.dragStateChanged.connect(self._on_drag_state_changed)
        self.scene.addItem(new_node)
        self.node_items[new_node.node_id] = new_node
        self._auto_scale_view()

        predecessor_id = self.order[index - 1] if index > 0 else None
        successor_id = self.order[index] if index < len(self.order) else None

        # 构建动画序列（关键！）
        traversal = self._build_traversal_anim(index)                       # 遍历前index个节点（蓝色闪烁）
        fade_in = self.anim.parallel(                                       # 并行动画：淡入+下落
            self.anim.move_item(new_node, target_position, duration=650),
            self.anim.fade_item(new_node, 0.0, 1.0, duration=650),
        )

        flash_new = self.anim.flash_brush(      # 新节点红色闪烁2次
            setter=new_node.setFillColor,
            start_color=new_node.fillColor,
            end_color=QColor("#ff4d4d"),
            duration=400,
            loops=2,
        )

        forward_arrow_anim = self._animate_new_arrow_link(new_node, successor_id)   # 绘制指向后继的箭头
        if forward_arrow_anim is None:
            forward_arrow_anim = self.anim.pause(100)

        arrow_transition, arrow_restore = (None, None)
        if successor_id is not None:
            arrow_transition, arrow_restore = self._build_arrow_transition(
                predecessor_id, successor_id, new_node.node_id
            )

        tail_insertion = successor_id is None and predecessor_id is not None

        if tail_insertion:
            predecessor_anim = self.anim.pause(80)
        else:
            predecessor_anim = arrow_transition if arrow_transition else self.anim.pause(80)

        # 组合成顺序动画
        combined = self.anim.sequential(
            traversal,          # 1. 遍历
            fade_in,            # 2. 淡入
            flash_new,          # 3. 闪烁
            forward_arrow_anim, # 4. 箭头动画
            predecessor_anim,   # 5. 前驱箭头重定向
        )

        def _finalizer():
            self._finalize_insert(nodes, new_node, index)

            if tail_insertion:
                tail_anim, tail_restore = self._build_tail_arrow_extension(
                    predecessor_id, new_node.node_id
                )
                if tail_anim:
                    self._track_animation(
                        tail_anim,
                        finalizer=(lambda: tail_restore() if tail_restore else None),
                    )
            else:
                if arrow_restore:
                    arrow_restore()

        # 执行动画并设置回调
        self._track_animation(combined, finalizer=_finalizer)

    def animate_delete(self, nodes, removed_id, index):
        target_node = self.node_items.get(removed_id)
        if not target_node:
            return
        # 1. 计算前驱和后继节点
        traversal = self.anim.pause(50)
        predecessor_id = self.order[index - 1] if index > 0 else None
        successor_id = self.order[index + 1] if index + 1 < len(self.order) else None
        # 2. 构建动画序列
        flash = self.anim.flash_brush(
            setter=target_node.setFillColor,
            start_color=target_node.fillColor,
            end_color=QColor("#ff4d4d"),    # 红色闪烁
            duration=400,
            loops=2,
        )
        # 3. 箭头重定向动画（关键！）
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
        # 5. 组合成顺序动画
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
        # 1. 同步最新数据顺序
        self.order = [node["id"] for node in nodes]
        changed_items = []
        # 2. 遍历所有节点，比较新旧值
        for info in nodes:
            node_item = self.node_items.get(info["id"])
            if not node_item:
                continue

            new_value = str(info["value"])
            value_changed = node_item.value() != new_value
            node_item.set_value(new_value)

            if value_changed: # 将发生变化的节点加入待动画列表
                changed_items.append(node_item)
        # 3. 如果没有变化，直接重绘箭头并返回
        if not changed_items:
            self._refresh_connectivity()
            return
        # 4. 为每个变化节点创建并行闪烁动画
        flashes = [
            self.anim.flash_brush(
                setter=item.setFillColor,       # 动画目标：填充色
                start_color=item.fillColor,     # 起始颜色（原色）
                end_color=QColor("#4dd0e1"),    # 结束颜色（青色）
                duration=360,                   # 单次时长
                loops=2,                        # 闪烁2次（青→原→青→原）
            )
            for item in changed_items
        ]
        # 5. 所有闪烁动画并行执行
        group = self.anim.parallel(*flashes)
        # 6. 动画结束后重建箭头
        self._track_animation(group, finalizer=self._refresh_connectivity)

    # ---------- Helpers ----------
    """根据节点ID查找其在链表中的索引位置。"""
    def index_of(self, node_id):
        return self.order.index(node_id) if node_id in self.order else -1

    """插入动画完全结束后调用的回调函数，用于永久化插入操作"""
    def _finalize_insert(self, nodes, new_node, index):
        self.order.insert(index, new_node.node_id)
        self.node_items[new_node.node_id] = new_node
        self.order = [node["id"] for node in nodes]
        self._refresh_connectivity()

    """删除动画完全结束后调用的回调函数，用于彻底清理被删除的节点"""
    def _finalize_delete(self, nodes, removed_id):
        node = self.node_items.pop(removed_id, None)
        if node:
            self.scene.removeItem(node)
        self.order = [node["id"] for node in nodes]
        self._refresh_connectivity()

    """根据当前节点顺序完整重建所有箭头连接"""
    def _rebuild_arrows(self):
        # 清空现有箭头
        self._clear_arrows()
        # 链表节点数小于2时，无需箭头
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
            # 决定箭头弧线方向
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

    # 计算一个节点的位置是valley、peak还是其他
    def _classify_nodes_by_height(self, centers):
        classifications = {}
        for idx, node_id in enumerate(self.order):
            if node_id not in centers:
                classifications[node_id] = None
                continue
            y = centers[node_id].y()
            prev_id = self.order[idx - 1] if idx > 0 else None
            next_id = self.order[idx + 1] if idx < len(self.order) - 1 else None
            prev_y = centers[prev_id].y() if prev_id is not None and prev_id in centers else None
            next_y = centers[next_id].y() if next_id is not None and next_id in centers else None

            if prev_y is None or next_y is None:
                classifications[node_id] = None
                continue

            if y > prev_y and y > next_y: #
                classifications[node_id] = "valley"
            elif y < prev_y and y < next_y: #
                classifications[node_id] = "peak"
            else:
                classifications[node_id] = None
        return classifications

    # 确定箭头弧度是向上还是向下
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

    # 箭头指向的平滑过渡
    def _build_arrow_transition(self, predecessor_id, removed_id, successor_id):
        if predecessor_id is None:
            return self.anim.pause(60), None
        # 获取当前箭头（前驱 → 被删节点）
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

    def _build_tail_arrow_extension(self, predecessor_id, new_node_id, duration=720):
        arrow = self.arrow_items.get((predecessor_id, new_node_id))
        if arrow is None:
            return None, None

        start_item = arrow.start_item
        end_item = arrow.end_item
        if start_item is None or end_item is None:
            return None, None

        start_center = start_item.mapToScene(start_item.pointer_center())
        hover_target = QPointF(
            start_center.x() + max(22.0, start_item.pointer_size * 0.8),
            start_center.y(),
        )
        end_center = end_item.mapToScene(
            end_item.pointer_virtual_predecessor_center()
        )

        arrow.set_override_target(hover_target)
        arrow.update_path()

        arrow_ref = lambda: arrow if arrow.scene() is not None else None

        current_pen = QPen(arrow.pen())
        start_color = QColor(current_pen.color())
        start_width = float(current_pen.widthF())
        highlight_color = QColor("#ff1744")
        highlight_width = max(5.0, start_width + 1.5)

        highlight = self._animate_arrow_style(
            arrow_ref=arrow_ref,
            start_color=start_color,
            end_color=highlight_color,
            start_width=start_width,
            end_width=highlight_width,
            duration=360,
        )

        extension = QVariantAnimation()
        extension.setDuration(self.anim.global_ctrl.scale_duration(duration))
        extension.setStartValue(0.0)
        extension.setEndValue(1.0)

        def _update(progress):
            arrow_obj = arrow_ref()
            if arrow_obj is None:
                return
            interp = QPointF(
                hover_target.x() + (end_center.x() - hover_target.x()) * progress,
                hover_target.y() + (end_center.y() - hover_target.y()) * progress,
            )
            arrow_obj.set_override_target(interp)

        def _finish():
            arrow_obj = arrow_ref()
            if arrow_obj is None:
                return
            arrow_obj.set_override_target(None)
            arrow_obj.update_path()

        extension.valueChanged.connect(_update)
        extension.finished.connect(_finish)

        seq = self.anim.sequential(
            self.anim.pause(40),
            highlight,
            self.anim.pause(120),
            extension,
            self.anim.pause(100),
        )

        default_color = arrow.default_pen_color()
        default_width = arrow.default_pen_width()

        def _restore_style():
            arrow_obj = arrow_ref()
            if arrow_obj is None:
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

        start_center = start_node.mapToScene(start_node.pointer_center())
        end_center = successor_item.mapToScene(
            successor_item.pointer_virtual_predecessor_center()
        )

        hover_target = QPointF(
            start_center.x() + max(22.0, start_node.pointer_size * 0.8),
            start_center.y(),
        )

        arrow = ArrowItem(start_node, successor_item, orientation="right")
        arrow.setOpacity(0.0)
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
            return None

        arrow = holder.get("arrow")
        if arrow is None:
            return None

        old_end_item = self.node_items.get(removed_id)
        new_end_item = self.node_items.get(successor_id)
        if old_end_item is None or new_end_item is None:
            return None

        start_point = old_end_item.mapToScene(
            old_end_item.pointer_virtual_predecessor_center()
        )
        end_point = new_end_item.mapToScene(
            new_end_item.pointer_virtual_predecessor_center()
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

            original_color = QColor(node_item.fillColor)

            flash = self.anim.flash_brush(
                setter=node_item.setFillColor,
                start_color=original_color,
                end_color=QColor("#4fc3f7"),
                duration=400,
                loops=1,
            )

            def _restore(color=original_color, item=node_item):
                item.setFillColor(color)

            flash.finished.connect(_restore)
            seq.addAnimation(flash)

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

    # 计算新节点放置的位置
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
        self._update_head_label()
        self._update_tail_markers()
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
            QPointF(LinkedListNodeItem.width / 2, 0)
        )
        label_rect = self._head_label.boundingRect()
        self._head_label.setPos(
            top_center.x() - label_rect.width() / 2,
            top_center.y() - label_rect.height() - 12,
        )
        self._head_label.setVisible(True)

    def _update_tail_markers(self):
        tail_id = self.order[-1] if self.order else None
        for node_id, node_item in self.node_items.items():
            node_item.set_tail(node_id == tail_id)

    def _auto_scale_view(self, padding=120):
        self.auto_fit_view(padding=padding, skip_if=lambda: self._dragging)

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

    height = 50
    pointer_size = height
    data_base_width = 100
    width = data_base_width + pointer_size  # 兼容旧逻辑

    def __init__(self, node_id, value):
        super().__init__()
        self.node_id = node_id
        self._value = str(value)
        self.fillColor = QColor("#e9e9ef")
        self.strokeColor = QColor("#4a4a52")
        self.textColor = QColor("#1f1f24")
        self.data_width = self.data_base_width
        self._label_font = self._create_label_font()
        self._is_tail = False

        self.setFlags(
            QGraphicsItem.ItemIsMovable
            | QGraphicsItem.ItemIsSelectable
            | QGraphicsItem.ItemSendsGeometryChanges
        )

        self._adjust_data_width()

    def boundingRect(self):
        return QRectF(0, 0, self.total_width(), self.height)

    def paint(self, painter, option, widget=None):
        painter.setRenderHint(painter.Antialiasing)

        outer_rect = self.boundingRect()
        divider_x = self.data_width

        outline_pen = QPen(self.strokeColor, 2.2)
        painter.setPen(outline_pen)
        painter.setBrush(QBrush(self.fillColor))
        painter.drawRect(outer_rect)

        divider_pen = QPen(self.strokeColor, 1.8)
        painter.setPen(divider_pen)
        painter.drawLine(
            QPointF(divider_x, 1.0),
            QPointF(divider_x, self.height - 1.0),
        )

        painter.setFont(self._label_font)
        painter.setPen(self.textColor)
        text_rect = QRectF(0, 0, self.data_width, self.height).adjusted(10, 0, -10, 0)
        painter.drawText(text_rect, Qt.AlignCenter, self._value)

        if self._is_tail:
            pointer_text_rect = self.pointer_rect().adjusted(4, 4, -4, -4)
            tail_font = QFont(self._label_font)
            tail_font.setPointSize(7)  # 明确设置更小字号，防止被截断
            tail_font.setBold(True)  # 加粗
            painter.setFont(tail_font)
            painter.setPen(self.strokeColor)
            painter.drawText(pointer_text_rect, Qt.AlignCenter, "NULL")

    def value(self):
        return self._value

    def set_value(self, value: str):
        self._value = str(value)
        self._adjust_data_width()
        self.update()

    def setFillColor(self, color: QColor):
        self.fillColor = QColor(color)
        self.update()

    def setStrokeColor(self, color: QColor):
        self.strokeColor = QColor(color)
        self.update()

    def set_tail(self, is_tail: bool):
        if self._is_tail != is_tail:
            self._is_tail = is_tail
            self.update()

    def total_width(self):
        return self.data_width + self.pointer_size

    def data_rect(self):
        return QRectF(0, 0, self.data_width, self.height)

    def pointer_rect(self):
        return QRectF(self.data_width, 0, self.pointer_size, self.pointer_size)

    def pointer_center(self):
        return QPointF(self.data_width + self.pointer_size / 2.0, self.height / 2.0)

    def pointer_entry_point(self):
        return self.pointer_center()

    def pointer_virtual_predecessor_center(self):
        square_size = self.pointer_size * 0.8
        half_square = square_size / 2.0
        center_x = min(self.data_width - half_square, half_square)
        center_x = max(half_square, center_x)
        return QPointF(center_x, self.height / 2.0)

    def center_point(self):
        return QPointF(self.total_width() / 2.0, self.height / 2.0)

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

    def _create_label_font(self):
        font = QFont()
        font.setPointSize(14)
        return font

    def _adjust_data_width(self):
        metrics = QFontMetrics(self._label_font)
        padding = 32
        required = metrics.horizontalAdvance(self._value) + padding
        new_data_width = max(self.data_base_width, required)

        if new_data_width != self.data_width:
            self.prepareGeometryChange()
            self.data_width = new_data_width

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
        self.setZValue(5)  # 确保箭头绘制在节点之后

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
            self.start_item.pointer_center()
        )

        if self._override_target is not None:
            target_center = self._override_target
        else:
            target_center = self.end_item.mapToScene(
                self.end_item.pointer_virtual_predecessor_center()
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