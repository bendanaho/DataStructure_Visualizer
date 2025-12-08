import math
from typing import Dict, List, Optional, Set, Tuple

from PyQt5.QtCore import QEvent, QPointF, QRectF, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QBrush, QPen, QPainterPath
from PyQt5.QtWidgets import (
    QGraphicsItem,
    QGraphicsObject,
    QGraphicsPathItem,
    QMenu,
)

from core.base_view import BaseStructureView


class HuffmanView(BaseStructureView):
    """
    三阶段可视化：
    1. 数列依次飞入至底部；
    2. 通过插入排序展示重排过程；
    3. 按哈夫曼构建步骤反复选取最小节点，在中央合并并生成父节点，最后落位成树。
    """

    def __init__(self, global_ctrl):
        super().__init__(global_ctrl)
        self.scene.installEventFilter(self)

        self.node_items: Dict[int, HuffmanNodeItem] = {}
        self.edge_items: Dict[Tuple[int, int], HuffmanEdgeItem] = {}
        self.tree_structure: Dict[int, Dict[str, Optional[int]]] = {}
        self.node_depths: Dict[int, int] = {}
        self.leaf_counts: Dict[int, int] = {}
        self.queue_order: List[int] = []
        self.in_queue_ids: Set[int] = set()

        self._queue_y = 240
        self._queue_spacing = HuffmanNodeItem.width + 18
        self._level_gap = 120
        self._first_merge_centered = False

    # ---------- 生命周期 ----------

    def reset(self):
        self.stop_all_animations()
        # 逐条边断开 signal-slot，防止场景清空后访问悬空对象
        for edge in list(self.edge_items.values()):
            edge.dispose()
            if edge.scene():
                self.scene.removeItem(edge)
        self.scene.clear()
        self.node_items.clear()
        self.edge_items.clear()
        self.tree_structure.clear()
        self.node_depths.clear()
        self.leaf_counts.clear()
        self.queue_order.clear()
        self.in_queue_ids.clear()
        self._first_merge_centered = False

    def play_process(self, timeline):
        self.reset()

        initial = timeline.get("initial") or []
        sorting = timeline.get("sorting") or []
        building = timeline.get("building") or []
        final_tree = timeline.get("final_tree")

        sequence = self.anim.sequential()
        if initial:
            sequence.addAnimation(self._animate_initial_fly_in(initial))
        if sorting:
            sequence.addAnimation(self._animate_insertion_sort(sorting))
        if building:
            sequence.addAnimation(self._animate_build_phase(building, final_tree))
        elif final_tree:
            sequence.addAnimation(self._animate_final_layout(final_tree))

        if sequence.animationCount() == 0:
            return
        self._track_animation(sequence, finalizer=self._auto_scale_view)

    # ---------- 初始飞入 ----------

    def _animate_initial_fly_in(self, nodes: List[Dict]):
        self.queue_order = [info["id"] for info in nodes]
        self.in_queue_ids = set(self.queue_order)

        positions = self._queue_positions(len(nodes))
        sequence = self.anim.sequential()

        for idx, info in enumerate(nodes):
            node_id = info["id"]
            value = info["value"]
            item = self._create_node_item(node_id, value)
            start = QPointF(positions[idx].x(), positions[idx].y() - 220)
            item.setPos(start)
            item.setOpacity(0.0)

            fly = self.anim.move_item(item, positions[idx], duration=420)
            fade = self.anim.fade_item(item, 0.0, 1.0, duration=420)
            sequence.addAnimation(self.anim.parallel(fly, fade))

            self.tree_structure[node_id] = {"value": value, "left": None, "right": None}
            self.node_depths[node_id] = 0
            self.leaf_counts[node_id] = 1

        return sequence

    def _queue_positions(self, count: int):
        if count == 0:
            return []
        offset = ((count - 1) * self._queue_spacing) / 2.0
        return [
            QPointF(idx * self._queue_spacing - offset, self._queue_y)
            for idx in range(count)
        ]

    # ---------- 插入排序动画 ----------

    def _animate_insertion_sort(self, steps: List[Dict]):
        if not steps:
            return self.anim.pause(0)

        sequence = self.anim.sequential()
        for step in steps:
            sequence.addAnimation(self._animate_insert_step(step))
        return sequence

    def _animate_insert_step(self, step: Dict):
        order_before = list(step["array_before"])
        key_id = step["key_id"]
        from_idx = step["from_index"]
        insert_idx = step["insert_index"]

        if order_before != self.queue_order:
            self.queue_order = order_before[:]

        if from_idx == insert_idx:
            return self.anim.pause(0)

        positions = self._queue_positions(len(order_before))
        idx_pos = {idx: positions[idx] for idx in range(len(positions))}
        hover_height = 120

        key_item = self.node_items.get(key_id)
        if not key_item:
            return self.anim.pause(0)

        raise_duration = 180        # 原 360 → 加速 2×
        hover_duration = 160        # 原 320 → 加速 2×
        shift_duration = 160        # 原 320 → 加速 2×
        drop_duration = 180         # 原 360 → 加速 2×

        sequence = self.anim.sequential()
        raise_target = QPointF(idx_pos[from_idx].x(), idx_pos[from_idx].y() - hover_height)
        sequence.addAnimation(self.anim.move_item(key_item, raise_target, duration=raise_duration))

        hover_target = QPointF(idx_pos[insert_idx].x(), raise_target.y())
        sequence.addAnimation(self.anim.move_item(key_item, hover_target, duration=hover_duration))

        shift_motions = []
        if insert_idx < from_idx:
            for idx in range(insert_idx, from_idx):
                current_id = order_before[idx]
                if current_id == key_id:
                    continue
                item = self.node_items.get(current_id)
                if not item:
                    continue
                target = QPointF(idx_pos[idx + 1].x(), self._queue_y)
                shift_motions.append(self.anim.move_item(item, target, duration=shift_duration))
        else:
            for idx in range(from_idx + 1, insert_idx + 1):
                current_id = order_before[idx]
                item = self.node_items.get(current_id)
                if not item:
                    continue
                target = QPointF(idx_pos[idx - 1].x(), self._queue_y)
                shift_motions.append(self.anim.move_item(item, target, duration=shift_duration))

        if shift_motions:
            sequence.addAnimation(self.anim.parallel(*shift_motions))

        drop_target = QPointF(idx_pos[insert_idx].x(), self._queue_y)
        sequence.addAnimation(self.anim.move_item(key_item, drop_target, duration=drop_duration))

        order_after = order_before[:]
        value = order_after.pop(from_idx)
        order_after.insert(insert_idx, value)
        self.queue_order = order_after

        return sequence

    # ---------- 构建阶段动画 ----------

    def _animate_build_phase(self, steps: List[Dict], final_snapshot: Optional[Dict]):
        sequence = self.anim.sequential()
        if not steps:
            if final_snapshot:
                sequence.addAnimation(self._animate_final_layout(final_snapshot))
            return sequence

        for step in steps:
            sequence.addAnimation(self._animate_merge_step(step))

        if final_snapshot:
            sequence.addAnimation(self._animate_final_layout(final_snapshot))
        return sequence

    def _animate_merge_step(self, step: Dict):
        left_id = step["left_id"]
        right_id = step["right_id"]
        geometry = self._determine_stage_positions(left_id, right_id)

        sequence = self.anim.sequential()
        sequence.addAnimation(
            self.anim.parallel(
                self._flash_node(left_id, QColor("#ff5252")),
                self._flash_node(right_id, QColor("#ff5252")),
            )
        )

        move_left = self._move_subtree_to_target(left_id, geometry["left_target"])
        move_right = self._move_subtree_to_target(right_id, geometry["right_target"])
        sequence.addAnimation(self.anim.parallel(move_left, move_right))

        if not self._first_merge_centered:
            sequence.addAnimation(self._ensure_stage_centered())
            self._first_merge_centered = True

        removed = False
        for node_id in (left_id, right_id):
            if node_id in self.in_queue_ids:
                self.in_queue_ids.remove(node_id)
                if node_id in self.queue_order:
                    self.queue_order.remove(node_id)
                    removed = True
        if removed:
            sequence.addAnimation(self._compress_queue())

        sequence.addAnimation(self._animate_parent_creation(step["parent"], geometry["parent_pos"]))
        sequence.addAnimation(self._animate_tree_relayout())
        return sequence

    def _determine_stage_positions(self, left_id: int, right_id: int):
        """
        计算合并阶段的位置。
        修复逻辑：
        1. 如果节点已在树中（Fixed），保持不动。
        2. 如果一个Fixed一个New，New的位置必须相对于Fixed的位置计算。
        3. 【新增】强制对齐：新插入节点的Y坐标必须与兄弟节点一致，而不是使用默认深度高度。
        """
        # 1. 获取基础数据
        left_span = max(1, self.leaf_counts.get(left_id, 1))
        right_span = max(1, self.leaf_counts.get(right_id, 1))

        # 默认高度计算（仅当两个都是新节点时使用此基准）
        parent_depth = max(self.node_depths.get(left_id, 0), self.node_depths.get(right_id, 0)) + 1
        default_base_y = 120 - parent_depth * self._level_gap

        # 2. 判断节点状态：是否已固定在画面上（不在队列中即为已固定）
        is_left_fixed = (left_id not in self.in_queue_ids) and (left_id in self.node_items)
        is_right_fixed = (right_id not in self.in_queue_ids) and (right_id in self.node_items)

        # 3. 计算需要的水平间距
        spacing_unit = 40
        total_span = left_span + right_span
        separation = max(100, total_span * spacing_unit)

        left_target = QPointF()
        right_target = QPointF()

        # 4. 根据四种情况计算目标位置
        if not is_left_fixed and not is_right_fixed:
            # 情况 A: 两个都是新节点 -> 以 0 为中心对称，使用默认高度
            left_target = QPointF(-separation / 2, default_base_y)
            right_target = QPointF(separation / 2, default_base_y)

        elif is_left_fixed and not is_right_fixed:
            # 情况 B: 左边是旧树，右边是新节点
            current_left_pos = self.node_items[left_id].pos()
            left_target = current_left_pos  # 左边不动

            # 右节点位置 = 左节点X + 间距，高度强制与左节点一致
            right_target = QPointF(current_left_pos.x() + separation, current_left_pos.y())

        elif not is_left_fixed and is_right_fixed:
            # 情况 C: 右边是旧树，左边是新节点
            current_right_pos = self.node_items[right_id].pos()
            right_target = current_right_pos  # 右边不动

            # 左节点位置 = 右节点X - 间距，高度强制与右节点一致
            left_target = QPointF(current_right_pos.x() - separation, current_right_pos.y())

        else:
            # 情况 D: 两个都是旧树 -> 都保持不动
            left_target = self.node_items[left_id].pos()
            right_target = self.node_items[right_id].pos()

        # 5. 计算父节点位置（居中于两个子节点上方）
        def get_center(p: QPointF):
            return QPointF(
                p.x() + HuffmanNodeItem.width / 2,
                p.y() + HuffmanNodeItem.height / 2,
            )

        lc = get_center(left_target)
        rc = get_center(right_target)

        parent_center_x = (lc.x() + rc.x()) / 2.0
        # 父节点高度取两者中较高者（y值较小者）的上方
        # 注意：现在因为强制对齐了Y轴，lc.y() 和 rc.y() 通常是一样的
        parent_center_y = min(lc.y(), rc.y()) - self._level_gap

        parent_pos = QPointF(
            parent_center_x - HuffmanNodeItem.width / 2,
            parent_center_y - HuffmanNodeItem.height / 2,
        )

        return {
            "left_target": left_target,
            "right_target": right_target,
            "parent_pos": parent_pos,
        }

    def _ensure_stage_centered(self):
        anim = self.anim.pause(0)

        def _on_finish():
            self._auto_scale_view()

        anim.finished.connect(_on_finish)
        return anim

    def _move_subtree_to_target(self, node_id: Optional[int], target: QPointF):
        if node_id is None or node_id not in self.node_items:
            return self.anim.pause(0)

        nodes = self._collect_subtree_nodes(node_id)
        if not nodes:
            return self.anim.pause(0)

        root_item = self.node_items[node_id]
        start_pos = QPointF(root_item.pos())
        delta = target - start_pos
        if abs(delta.x()) < 1e-2 and abs(delta.y()) < 1e-2:
            return self.anim.pause(0)

        motions = []
        duration = self._build_duration(540)
        initial_positions = {nid: QPointF(self.node_items[nid].pos()) for nid in nodes}
        for nid in nodes:
            item = self.node_items[nid]
            goal = initial_positions[nid] + delta
            motions.append(self.anim.move_item(item, goal, duration=duration))
        return self.anim.parallel(*motions)

    def _collect_subtree_nodes(self, node_id: Optional[int]):
        result: List[int] = []

        def dfs(nid):
            if nid is None or nid not in self.node_items:
                return
            result.append(nid)
            info = self.tree_structure.get(nid)
            if not info:
                return
            dfs(info.get("left"))
            dfs(info.get("right"))

        dfs(node_id)
        return result

    def _animate_parent_creation(self, parent_info: Dict, parent_pos: QPointF):
        parent_id = parent_info["id"]
        value = parent_info["value"]
        left_id = parent_info["left"]
        right_id = parent_info["right"]

        parent_item = self._create_node_item(parent_id, value)

        # 深度：父节点高于子节点
        parent_depth = max(self.node_depths.get(left_id, 0), self.node_depths.get(right_id, 0)) + 1
        self.node_depths[parent_id] = parent_depth
        parent_item.setPos(parent_pos)
        parent_item.setOpacity(0.0)
        parent_item.setZValue(3 + parent_depth)

        self.tree_structure[parent_id] = {
            "value": value,
            "left": left_id,
            "right": right_id,
        }
        self.leaf_counts[parent_id] = self.leaf_counts.get(left_id, 1) + self.leaf_counts.get(right_id, 1)

        edges = []
        edge_fade_duration = self._build_duration(260)
        for child_id in (left_id, right_id):
            child_item = self.node_items.get(child_id)
            if not child_item:
                continue
            edge = HuffmanEdgeItem(parent_item, child_item)
            edge.setOpacity(0.0)
            self.scene.addItem(edge)
            self.edge_items[(parent_id, child_id)] = edge
            edges.append(edge)

        edge_seq = self.anim.sequential()
        for edge in edges:
            edge_seq.addAnimation(self.anim.fade_item(edge, 0.0, 1.0, duration=edge_fade_duration))

        fade_parent = self.anim.fade_item(
            parent_item,
            0.0,
            1.0,
            duration=self._build_duration(360),
        )
        if edge_seq.animationCount() == 0:
            return fade_parent
        return self.anim.sequential(edge_seq, fade_parent)

    def _compress_queue(self):
        if not self.queue_order:
            return self.anim.pause(0)
        positions = self._queue_positions(len(self.queue_order))
        motions = []
        duration = self._build_duration(320)
        for idx, node_id in enumerate(self.queue_order):
            item = self.node_items.get(node_id)
            if not item:
                continue
            target = positions[idx]
            if (item.pos() - target).manhattanLength() < 1e-2:
                continue
            motions.append(self.anim.move_item(item, target, duration=duration))
        if not motions:
            return self.anim.pause(0)
        return self.anim.parallel(*motions)

    # ---------- 最终落位 ----------

    def _animate_final_layout(self, snapshot: Dict):
        positions = self._compute_layout(snapshot)
        if not positions:
            return self.anim.pause(0)

        motions = []
        for node_id, target in positions.items():
            item = self.node_items.get(node_id)
            if not item:
                continue
            motions.append(self.anim.move_item(item, target, duration=680))

        group = self.anim.parallel(*motions) if motions else self.anim.pause(0)
        return self.anim.sequential(group, self.anim.pause(160))

    def _compute_layout(self, snapshot: Dict):
        root_id = snapshot.get("root")
        if root_id is None:
            return {}

        nodes = {node["id"]: node for node in snapshot.get("nodes", [])}
        positions: Dict[int, QPointF] = {}
        index = [0]
        h_gap = 120
        v_gap = 110

        def inorder(node_id, depth):
            if node_id is None or node_id not in nodes:
                return
            inorder(nodes[node_id]["left"], depth + 1)
            x = index[0] * h_gap
            y = depth * v_gap - 200
            positions[node_id] = QPointF(x, y)
            index[0] += 1
            inorder(nodes[node_id]["right"], depth + 1)

        inorder(root_id, 0)

        total = max(1, index[0])
        offset = ((total - 1) * h_gap) / 2.0
        for node_id, point in positions.items():
            positions[node_id] = QPointF(point.x() - offset, point.y())
        return positions

    # ---------- 辅助 ----------

    def _flash_node(self, node_id: int, color: QColor):
        item = self.node_items.get(node_id)
        if not item:
            return self.anim.pause(0)
        original = QColor(item.fillColor)

        highlight = self.anim.flash_brush(
            setter=item.setFillColor,
            start_color=original,
            end_color=color,
            duration=self._build_duration(220),
            loops=1,
        )
        recover = self.anim.flash_brush(
            setter=item.setFillColor,
            start_color=color,
            end_color=original,
            duration=self._build_duration(220),
            loops=1,
        )
        return self.anim.sequential(highlight, recover)

    def _animate_tree_relayout(self):
        positions = self._compute_current_layout()
        if not positions:
            group = self.anim.pause(0)
            group.finished.connect(self._auto_scale_view)
            return group

        motions = []
        duration = self._build_duration(520)
        for node_id, target in positions.items():
            item = self.node_items.get(node_id)
            if not item:
                continue
            if (item.pos() - target).manhattanLength() < 1e-2:
                continue
            motions.append(self.anim.move_item(item, target, duration=duration))

        group = self.anim.parallel(*motions) if motions else self.anim.pause(0)
        group.finished.connect(self._auto_scale_view)
        return group

    def _compute_current_layout(self):
        nodes = {
            node_id: data
            for node_id, data in self.tree_structure.items()
            if node_id not in self.in_queue_ids
        }
        if not nodes:
            return {}

        roots = self._find_current_roots(nodes)
        if not roots:
            return {}

        positions: Dict[int, QPointF] = {}
        index = [0]
        h_gap = 120
        v_gap = 110

        def inorder(node_id, depth):
            if node_id is None or node_id not in nodes:
                return
            inorder(nodes[node_id]["left"], depth + 1)
            x = index[0] * h_gap
            y = depth * v_gap - 200
            positions[node_id] = QPointF(x, y)
            index[0] += 1
            inorder(nodes[node_id]["right"], depth + 1)

        for root in roots:
            inorder(root, 0)

        total = max(1, index[0])
        offset = ((total - 1) * h_gap) / 2.0
        for node_id, point in positions.items():
            positions[node_id] = QPointF(point.x() - offset, point.y())
        return positions

    def _find_current_roots(self, nodes: Dict[int, Dict[str, Optional[int]]]):
        children: Set[int] = set()
        for data in nodes.values():
            for child in (data.get("left"), data.get("right")):
                if child is not None and child in nodes:
                    children.add(child)
        roots = [node_id for node_id in nodes if node_id not in children]
        roots.sort()
        return roots

    def _create_node_item(self, node_id: int, value):
        existing = self.node_items.get(node_id)
        if existing:
            existing.set_value(value)
            return existing
        item = HuffmanNodeItem(node_id, value)
        self.scene.addItem(item)
        self.node_items[node_id] = item
        return item

    def _show_background_menu(self, screen_pos):
        if isinstance(screen_pos, QPointF):
            screen_pos = screen_pos.toPoint()
        menu = QMenu()
        clear_action = menu.addAction("Clear")
        chosen = menu.exec_(screen_pos)
        if chosen == clear_action:
            self.reset()

    def eventFilter(self, watched, event):
        if watched is self.scene and event.type() == QEvent.GraphicsSceneContextMenu:
            item = self.scene.itemAt(
                event.scenePos(),
                self._canvas.transform() if self._canvas else None,
            )
            if item is None:
                self._show_background_menu(event.screenPos())
                event.accept()
                return True
        return super().eventFilter(watched, event)

    def _build_duration(self, base_ms: int) -> int:
        """
        将构建阶段动画放慢至原来的 0.7 倍速度（时长 ≈ 原时长 / 0.7）。
        """
        slow_factor = 1 / 0.7
        return max(1, int(round(base_ms * slow_factor)))


class HuffmanNodeItem(QGraphicsObject):
    positionChanged = pyqtSignal()

    width = 70
    height = 70

    def __init__(self, node_id, value):
        super().__init__()
        self.node_id = node_id
        self._value = str(value)
        self.fillColor = QColor("#e9e9ef")
        self.strokeColor = QColor("#4a4a52")
        self.textColor = QColor("#1f1f24")
        self.setZValue(2)
        self.setFlag(QGraphicsItem.ItemIsSelectable, False)
        self.setFlag(QGraphicsItem.ItemSendsGeometryChanges, True)
        self.setAcceptedMouseButtons(Qt.NoButton)

    def boundingRect(self):
        return QRectF(0, 0, self.width, self.height)

    def paint(self, painter, option, widget=None):
        painter.setRenderHint(painter.Antialiasing)
        painter.setPen(QPen(self.strokeColor, 2))
        painter.setBrush(QBrush(self.fillColor))
        painter.drawEllipse(self.boundingRect())
        painter.setPen(self.textColor)
        painter.drawText(self.boundingRect(), Qt.AlignCenter, self._value)

    def set_value(self, value):
        self._value = f"{value:g}"
        self.update()

    def setFillColor(self, color: QColor):
        self.fillColor = QColor(color)
        self.update()

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionHasChanged:
            self.positionChanged.emit()
        return super().itemChange(change, value)


class HuffmanEdgeItem(QGraphicsObject):
    def __init__(self, parent_item: HuffmanNodeItem, child_item: HuffmanNodeItem):
        super().__init__()
        self.parent_item = parent_item
        self.child_item = child_item
        self._disposed = False
        self._path = QPainterPath()
        self._bounding_rect = QRectF()
        self._pen = QPen(QColor("#9e9e9e"), 2)
        self._pen.setCapStyle(Qt.RoundCap)
        self._pen.setJoinStyle(Qt.RoundJoin)

        self.setZValue(1)
        self.setAcceptedMouseButtons(Qt.NoButton)
        self.setFlag(QGraphicsItem.ItemIsSelectable, False)

        self.parent_item.positionChanged.connect(self.update_geometry)
        self.child_item.positionChanged.connect(self.update_geometry)
        self.update_geometry()

    def boundingRect(self):
        return self._bounding_rect

    def paint(self, painter, option, widget=None):
        painter.setRenderHint(painter.Antialiasing)
        painter.setPen(self._pen)
        painter.drawPath(self._path)

    def dispose(self):
        if self._disposed:
            return
        self._disposed = True
        try:
            self.parent_item.positionChanged.disconnect(self.update_geometry)
        except (TypeError, RuntimeError):
            pass
        try:
            self.child_item.positionChanged.disconnect(self.update_geometry)
        except (TypeError, RuntimeError):
            pass

    def __del__(self):
        self.dispose()

    def update_geometry(self):
        start = self._center(self.parent_item)
        end = self._center(self.child_item)

        direction = end - start
        length = math.hypot(direction.x(), direction.y())
        offset = HuffmanNodeItem.width / 2

        if length > 1e-6:
            ux = direction.x() / length
            uy = direction.y() / length
            start_point = start + QPointF(ux * offset, uy * offset)
            end_point = end - QPointF(ux * offset, uy * offset)
        else:
            start_point = end_point = start

        path = QPainterPath(start_point)
        path.lineTo(end_point)

        self.prepareGeometryChange()
        self._path = path
        # 给笔划留出 2px 的缓冲，避免裁剪
        self._bounding_rect = self._path.boundingRect().adjusted(-2, -2, 2, 2)
        self.update()

    @staticmethod
    def _center(node_item: HuffmanNodeItem):
        pos = node_item.scenePos()
        return QPointF(
            pos.x() + HuffmanNodeItem.width / 2,
            pos.y() + HuffmanNodeItem.height / 2,
        )