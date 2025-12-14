import math
from typing import Dict, List, Optional, Set, Tuple

from PyQt5.QtCore import QPointF, QRectF, Qt, pyqtSignal, QEvent
from PyQt5.QtGui import QColor, QBrush, QPen, QPainterPath, QTransform
from PyQt5.QtWidgets import (
    QGraphicsItem,
    QGraphicsObject,
    QGraphicsPathItem,
    QGraphicsSimpleTextItem,
    QMenu,
)

from core.base_view import BaseStructureView


class HuffmanView(BaseStructureView):
    """负责哈夫曼森林的可视化、排序与合并动画。"""

    saveRequested = pyqtSignal()
    loadRequested = pyqtSignal()

    def __init__(self, global_ctrl):
        super().__init__(global_ctrl)
        self.node_items: Dict[int, HuffmanNodeItem] = {}
        self.edge_items: Dict[Tuple[int, int], HuffmanEdgeItem] = {}
        self._baseline_positions: Dict[int, QPointF] = {}
        self._last_snapshot: Dict = {"roots": [], "nodes": [], "stage": "idle"}
        self._forest_spacing = 200      # 森林中相邻两棵树的距离（固定）
        self._node_gap_x = 40
        self._node_gap_y = 120
        self._baseline_y = 260

        # 安装场景事件过滤器，监听背景右键菜单
        self.scene.installEventFilter(self)

    # ---------- Public API ----------

    def reset(self):
        self.stop_all_animations()
        self.scene.clear()
        self.node_items.clear()
        self.edge_items.clear()
        self._baseline_positions.clear()
        self._last_snapshot = {"roots": [], "nodes": [], "stage": "idle"}

    def is_busy(self) -> bool:
        return bool(self._running)

    def render_snapshot(self, snapshot: Optional[Dict]):
        """外部直接渲染快照（用于载入文件后恢复视图）。"""
        if not snapshot or not snapshot.get("nodes"):
            self.reset()
            return
        positions = self._compute_layout(snapshot)
        self._finalize_snapshot(snapshot, positions=positions)

    def animate_initialize(self, snapshot: Dict):
        self.reset()
        self._baseline_positions = self._compute_baseline_positions(snapshot["roots"])
        sequence = self.anim.sequential()
        for root_id in snapshot["roots"]:
            info = self._node_info(snapshot, root_id)
            item = self._ensure_node_item(info)
            target = self._baseline_positions[root_id]
            spawn = QPointF(target.x(), target.y() + 160)
            item.setPos(spawn)
            item.setOpacity(0.0)
            drop = self.anim.move_item(item, target, duration=360)
            fade = self.anim.fade_item(item, 0.0, 1.0, duration=360)
            sequence.addAnimation(self.anim.parallel(drop, fade))
        self._track_animation(
            sequence,
            finalizer=lambda: self._finalize_snapshot(
                snapshot, positions=dict(self._baseline_positions)
            ),
        )

    def animate_sort_step(self, before_snapshot: Dict, after_snapshot: Dict, op: Dict):
        i, j = op["i"], op["j"]
        roots_before = before_snapshot.get("roots", [])
        if i >= len(roots_before) or j >= len(roots_before):
            self._finalize_snapshot(after_snapshot, positions=dict(self._baseline_positions))
            return

        a_id = roots_before[i]
        b_id = roots_before[j]
        pos_a = self._baseline_positions.get(a_id)
        pos_b = self._baseline_positions.get(b_id)
        if pos_a is None or pos_b is None:
            self._finalize_snapshot(after_snapshot, positions=dict(self._baseline_positions))
            return

        item_a = self.node_items.get(a_id) or self._ensure_node_item(self._node_info(after_snapshot, a_id))
        item_b = self.node_items.get(b_id) or self._ensure_node_item(self._node_info(after_snapshot, b_id))

        self._baseline_positions[a_id], self._baseline_positions[b_id] = pos_b, pos_a

        move_a = self.anim.move_item(item_a, pos_b, duration=420)
        move_b = self.anim.move_item(item_b, pos_a, duration=420)

        self._track_animation(
            self.anim.parallel(move_a, move_b),
            finalizer=lambda: self._finalize_snapshot(
                after_snapshot, positions=dict(self._baseline_positions)
            ),
        )

    def animate_full_sorting(self, steps: List[Tuple[Dict, Dict, Dict]]):
        if not steps:
            return

        final_after_snapshot = steps[-1][1]
        sequence = self.anim.sequential()
        animated = False

        for before_snapshot, after_snapshot, op in steps:
            i = op.get("i")
            j = op.get("j")
            roots_before = before_snapshot.get("roots", [])

            if (
                i is None
                or j is None
                or i >= len(roots_before)
                or j >= len(roots_before)
            ):
                continue

            a_id = roots_before[i]
            b_id = roots_before[j]
            pos_a = self._baseline_positions.get(a_id)
            pos_b = self._baseline_positions.get(b_id)
            if pos_a is None or pos_b is None:
                continue

            item_a = self.node_items.get(a_id) or self._ensure_node_item(self._node_info(after_snapshot, a_id))
            item_b = self.node_items.get(b_id) or self._ensure_node_item(self._node_info(after_snapshot, b_id))

            target_a = QPointF(pos_b)
            target_b = QPointF(pos_a)

            move_a = self.anim.move_item(item_a, target_a, duration=420)
            move_b = self.anim.move_item(item_b, target_b, duration=420)

            self._baseline_positions[a_id] = target_a
            self._baseline_positions[b_id] = target_b

            parallel = self.anim.parallel(move_a, move_b)
            if parallel:
                sequence.addAnimation(parallel)
                animated = True

        if animated:
            self._track_animation(
                sequence,
                finalizer=lambda snap=final_after_snapshot: self._finalize_snapshot(
                    snap, positions=dict(self._baseline_positions)
                ),
            )
        else:
            self._finalize_snapshot(final_after_snapshot, positions=dict(self._baseline_positions))

    def animate_merge_step(self, before_snapshot: Dict, after_snapshot: Dict, info: Dict):
        left_id = info["left_id"]
        right_id = info["right_id"]
        parent_id = info["parent_id"]

        left_item = self.node_items.get(left_id)
        right_item = self.node_items.get(right_id)
        if not left_item or not right_item:
            self._finalize_snapshot(after_snapshot, positions=self._compute_layout(after_snapshot))
            return

        restore_colors: List[Tuple[HuffmanNodeItem, QColor]] = []
        flash_left = self._highlight_node(left_item, restore_colors)
        flash_right = self._highlight_node(right_item, restore_colors)

        meeting_center_x = (self._node_center(left_item).x() + self._node_center(right_item).x()) / 2
        meeting_y = min(left_item.pos().y(), right_item.pos().y()) - 160

        width_map = self._subtree_widths(before_snapshot)
        left_width = width_map.get(left_id, HuffmanNodeItem.width)
        right_width = width_map.get(right_id, HuffmanNodeItem.width)
        center_gap = left_width / 2 + right_width / 2 + 2*self._node_gap_x
        left_center = meeting_center_x - center_gap / 2
        right_center = meeting_center_x + center_gap / 2

        left_target = QPointF(left_center - HuffmanNodeItem.width / 2, meeting_y)
        right_target = QPointF(right_center - HuffmanNodeItem.width / 2, meeting_y)

        move_left = self._move_subtree(before_snapshot, left_id, left_target - left_item.pos())
        move_right = self._move_subtree(before_snapshot, right_id, right_target - right_item.pos())

        parent_info = self._node_info(after_snapshot, parent_id)
        parent_item = self._ensure_node_item(parent_info)
        spawn = QPointF(meeting_center_x - HuffmanNodeItem.width / 2, meeting_y - HuffmanNodeItem.height - 70)
        parent_item.setPos(spawn)
        self.scene.setSceneRect(self.scene.itemsBoundingRect())
        parent_item.setOpacity(0.0)
        fade_parent = self.anim.fade_item(parent_item, 0.0, 1.0, duration=420)

        self._ensure_edge(parent_id, left_id)
        self._ensure_edge(parent_id, right_id)

        final_positions = self._compute_layout(after_snapshot)
        relayout = self._animate_to_positions(final_positions)

        sequence = self.anim.sequential()
        if flash_left or flash_right:
            sequence.addAnimation(self.anim.parallel(flash_left, flash_right))
        sequence.addAnimation(self.anim.parallel(move_left, move_right))
        sequence.addAnimation(fade_parent)
        if relayout:
            sequence.addAnimation(relayout)

        def _finalize():
            for item, color in restore_colors:
                if item and item.scene():
                    item.setFillColor(color)
            self._finalize_snapshot(after_snapshot, positions=final_positions)

        self._track_animation(sequence, finalizer=_finalize)

    # ---------- Event filtering (context menu) ----------

    def eventFilter(self, watched, event):
        if watched is self.scene and event.type() == QEvent.GraphicsSceneContextMenu:
            view = self.scene.views()[0] if self.scene.views() else None
            transform = view.transform() if view else QTransform()
            item = self.scene.itemAt(event.scenePos(), transform)
            if item is None:
                menu = QMenu()
                open_action = menu.addAction("打开快照…")
                save_action = menu.addAction("保存快照…")
                chosen = menu.exec_(event.screenPos())
                if chosen == open_action:
                    self.loadRequested.emit()
                elif chosen == save_action:
                    self.saveRequested.emit()
                event.accept()
                return True
        return super().eventFilter(watched, event)

    # ---------- Internal helpers ----------

    def _finalize_snapshot(self, snapshot: Dict, positions: Optional[Dict[int, QPointF]] = None):
        nodes_map = {node["id"]: node for node in snapshot.get("nodes", [])}
        keep_ids = set(nodes_map.keys())

        for node_id in list(self.node_items.keys()):
            if node_id not in keep_ids:
                item = self.node_items.pop(node_id)
                if item.scene():
                    self.scene.removeItem(item)

        if positions is None:
            positions = self._compute_layout(snapshot)

        for info in snapshot.get("nodes", []):
            item = self._ensure_node_item(info)
            target = positions.get(info["id"])
            if target:
                item.setPos(target)

        self._rebuild_edges(snapshot)
        self._last_snapshot = snapshot

        # 更新基线位置，方便后续排序动画
        roots = snapshot.get("roots", [])
        baseline_update: Dict[int, QPointF] = {}
        for root_id in roots:
            pos = positions.get(root_id)
            if pos:
                baseline_update[root_id] = QPointF(pos)
        if baseline_update:
            self._baseline_positions = baseline_update
        else:
            self._baseline_positions = self._compute_baseline_positions(roots)

        leaf_codes = self._compute_leaf_codes(snapshot)
        for node_id, item in self.node_items.items():
            item.set_code(leaf_codes.get(node_id))

        self._auto_scale_view()

    def _ensure_node_item(self, info: Dict) -> "HuffmanNodeItem":
        node_id = info["id"]
        item = self.node_items.get(node_id)
        if not item:
            item = HuffmanNodeItem(node_id)
            self.scene.addItem(item)
            self.node_items[node_id] = item
        item.set_payload(
            label=info.get("label", str(info["id"])),
            weight=info.get("weight", 0),
            is_leaf=info.get("is_leaf", True),
        )
        return item

    def _ensure_edge(self, parent_id: int, child_id: int):
        key = (parent_id, child_id)
        if key in self.edge_items:
            return
        parent_item = self.node_items.get(parent_id)
        child_item = self.node_items.get(child_id)
        if not parent_item or not child_item:
            return
        edge = HuffmanEdgeItem(parent_item, child_item)
        edge.setZValue(0)
        self.scene.addItem(edge)
        self.edge_items[key] = edge

    def _rebuild_edges(self, snapshot: Dict):
        for edge in list(self.edge_items.values()):
            if edge.scene():
                self.scene.removeItem(edge)
        self.edge_items.clear()

        nodes_map = {node["id"]: node for node in snapshot.get("nodes", [])}
        for info in nodes_map.values():
            parent_id = info["id"]
            for child_key in ("left", "right"):
                child_id = info.get(child_key)
                if child_id is None:
                    continue
                self._ensure_edge(parent_id, child_id)

    def _compute_baseline_positions(self, roots: List[int]) -> Dict[int, QPointF]:
        count = len(roots)
        if count == 0:
            return {}
        spacing = HuffmanNodeItem.width + 36
        total_width = spacing * max(count - 1, 0)
        start_x = -total_width / 2
        positions: Dict[int, QPointF] = {}
        for idx, node_id in enumerate(roots):
            x = start_x + idx * spacing
            positions[node_id] = QPointF(x, self._baseline_y)
        return positions

    def _compute_layout(self, snapshot: Dict) -> Dict[int, QPointF]:
        roots = snapshot.get("roots", [])
        nodes = snapshot.get("nodes", [])
        if not roots or not nodes:
            return {}

        nodes_map = {node["id"]: node for node in nodes}
        width_cache: Dict[int, float] = {}
        positions: Dict[int, QPointF] = {}

        def subtree_width(node_id: Optional[int]) -> float:
            if node_id is None or node_id not in nodes_map:
                return 0.0
            if node_id in width_cache:
                return width_cache[node_id]

            node = nodes_map[node_id]
            left = subtree_width(node.get("left"))
            right = subtree_width(node.get("right"))
            node_width = HuffmanNodeItem.width

            if left and right:
                width = left + self._node_gap_x + right
            elif left:
                width = max(node_width, left + self._node_gap_x)
            elif right:
                width = max(node_width, right + self._node_gap_x)
            else:
                width = node_width

            width_cache[node_id] = width
            return width

        def assign(node_id: Optional[int], center_x: float, depth: int):
            if node_id is None or node_id not in nodes_map:
                return
            y = depth * self._node_gap_y
            positions[node_id] = QPointF(center_x - HuffmanNodeItem.width / 2, y)
            node = nodes_map[node_id]
            left_id = node.get("left")
            right_id = node.get("right")

            if left_id and right_id:
                left_width = subtree_width(left_id)
                right_width = subtree_width(right_id)
                left_center = center_x - (self._node_gap_x + right_width) / 2 - left_width / 2
                right_center = center_x + (self._node_gap_x + left_width) / 2 + right_width / 2
                assign(left_id, left_center, depth + 1)
                assign(right_id, right_center, depth + 1)
            elif left_id:
                assign(left_id, center_x - self._node_gap_x / 2, depth + 1)
            elif right_id:
                assign(right_id, center_x + self._node_gap_x / 2, depth + 1)

        tree_widths = [subtree_width(root_id) for root_id in roots]
        total_width = sum(tree_widths) + self._forest_spacing * max(len(roots) - 1, 0)
        cursor = -total_width / 2
        for width, root_id in zip(tree_widths, roots):
            center = cursor + width / 2
            assign(root_id, center, 0)
            cursor += width + self._forest_spacing

        if positions:
            min_y = min(pos.y() for pos in positions.values())
            for node_id in positions:
                positions[node_id] = QPointF(positions[node_id].x(), positions[node_id].y() - min_y + 120)

        return positions

    def _subtree_widths(self, snapshot: Dict) -> Dict[int, float]:
        nodes = snapshot.get("nodes", [])
        if not nodes:
            return {}
        nodes_map = {node["id"]: node for node in nodes}
        width_cache: Dict[int, float] = {}

        def helper(node_id: Optional[int]) -> float:
            if node_id is None or node_id not in nodes_map:
                return 0.0
            if node_id in width_cache:
                return width_cache[node_id]
            node = nodes_map[node_id]
            left = helper(node.get("left"))
            right = helper(node.get("right"))
            node_width = HuffmanNodeItem.width
            if left and right:
                width = left + self._node_gap_x + right
            elif left:
                width = max(node_width, left + self._node_gap_x)
            elif right:
                width = max(node_width, right + self._node_gap_x)
            else:
                width = node_width
            width_cache[node_id] = width
            return width

        for node in nodes:
            helper(node["id"])
        return width_cache

    def _node_info(self, snapshot: Dict, node_id: int) -> Dict:
        for info in snapshot.get("nodes", []):
            if info["id"] == node_id:
                return info
        raise KeyError(f"Node {node_id} not found")

    def _highlight_node(self, item: "HuffmanNodeItem", restore: List[Tuple["HuffmanNodeItem", QColor]]):
        original = QColor(item.fillColor)
        restore.append((item, original))
        return self.anim.flash_brush(
            setter=item.setFillColor,
            start_color=original,
            end_color=QColor("#ffb74d"),
            duration=360,
            loops=2,
        )

    def _move_subtree(self, snapshot: Dict, root_id: int, delta: QPointF):
        node_ids = self._collect_subtree_ids(snapshot, root_id)
        motions = []
        for node_id in node_ids:
            item = self.node_items.get(node_id)
            if not item:
                continue
            target = item.pos() + delta
            motions.append(self.anim.move_item(item, target, duration=520))
        return self.anim.parallel(*motions) if motions else self.anim.pause(1)

    def _collect_subtree_ids(self, snapshot: Dict, root_id: int) -> Set[int]:
        nodes_map = {node["id"]: node for node in snapshot.get("nodes", [])}
        result: Set[int] = set()
        stack = [root_id]
        while stack:
            node_id = stack.pop()
            if node_id in result or node_id not in nodes_map:
                continue
            result.add(node_id)
            node = nodes_map[node_id]
            if node.get("right"):
                stack.append(node["right"])
            if node.get("left"):
                stack.append(node["left"])
        return result

    def _animate_to_positions(self, positions: Dict[int, QPointF]):
        motions = []
        for node_id, target in positions.items():
            item = self.node_items.get(node_id)
            if not item:
                continue
            motions.append(self.anim.move_item(item, target, duration=560))
        return self.anim.parallel(*motions) if motions else None

    @staticmethod
    def _node_center(item: "HuffmanNodeItem") -> QPointF:
        pos = item.pos()
        return QPointF(pos.x() + HuffmanNodeItem.width / 2, pos.y() + HuffmanNodeItem.height / 2)

    def _compute_leaf_codes(self, snapshot: Dict) -> Dict[int, str]:
        stage = snapshot.get("stage")
        roots = snapshot.get("roots", [])
        nodes = snapshot.get("nodes", [])
        if stage != "complete" or len(roots) != 1 or not nodes:
            return {}

        nodes_map = {node["id"]: node for node in nodes}
        codes: Dict[int, str] = {}

        def dfs(node_id: Optional[int], prefix: str):
            if node_id is None or node_id not in nodes_map:
                return
            node = nodes_map[node_id]
            left_id = node.get("left")
            right_id = node.get("right")
            if left_id is None and right_id is None:
                codes[node_id] = prefix if prefix else "0"
                return
            if left_id is not None:
                dfs(left_id, prefix + "0")
            if right_id is not None:
                dfs(right_id, prefix + "1")

        dfs(roots[0], "")
        return codes


class HuffmanNodeItem(QGraphicsObject):
    positionChanged = pyqtSignal()

    width = 74
    height = 74

    def __init__(self, node_id: int):
        super().__init__()
        self.node_id = node_id
        self._label = str(node_id)
        self._is_leaf = True
        self.fillColor = QColor("#d1ecff")
        self.strokeColor = QColor("#37474f")
        self.textColor = QColor("#1f1f24")
        self.code_item = QGraphicsSimpleTextItem("", self)
        self.code_item.setBrush(QBrush(self.textColor))
        self.code_item.setVisible(False)
        self.setZValue(2)
        self.setFlag(QGraphicsItem.ItemIsSelectable, False)
        self.setFlag(QGraphicsItem.ItemSendsGeometryChanges, True)

    def boundingRect(self) -> QRectF:
        return QRectF(0, 0, self.width, self.height + 24)

    def paint(self, painter, option, widget=None):
        painter.setRenderHint(painter.Antialiasing)
        painter.setPen(QPen(self.strokeColor, 2))
        painter.setBrush(QBrush(self.fillColor))
        painter.drawEllipse(QRectF(0, 0, self.width, self.height))
        painter.setPen(self.textColor)
        painter.drawText(QRectF(0, 0, self.width, self.height), Qt.AlignCenter, self._label)

    def set_payload(self, label: str, weight: float, is_leaf: bool):
        self._label = label
        self._is_leaf = is_leaf
        base_color = QColor("#d1ecff") if is_leaf else QColor("#dcd1ff")
        self.setFillColor(base_color)
        self.update()

    def setFillColor(self, color: QColor):
        self.fillColor = QColor(color)
        self.update()

    def set_code(self, code: Optional[str]):
        if code:
            self.code_item.setText(code)
            self.code_item.setVisible(True)
            self._update_code_position()
        else:
            self.code_item.setText("")
            self.code_item.setVisible(False)

    def _update_code_position(self):
        if not self.code_item.isVisible():
            return
        rect = self.code_item.boundingRect()
        x = (self.width - rect.width()) / 2
        y = self.height + 4
        self.code_item.setPos(x, y)

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionHasChanged:
            self.positionChanged.emit()
        return super().itemChange(change, value)


class HuffmanEdgeItem(QGraphicsPathItem):
    def __init__(self, parent_item: HuffmanNodeItem, child_item: HuffmanNodeItem):
        super().__init__()
        self.parent_item = parent_item
        self.child_item = child_item

        pen = QPen(QColor("#9e9e9e"), 2)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        self.setPen(pen)
        self.setZValue(1)

        self.parent_item.positionChanged.connect(self.update_geometry)
        self.child_item.positionChanged.connect(self.update_geometry)
        self.update_geometry()

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
        self.setPath(path)

    @staticmethod
    def _center(node_item: HuffmanNodeItem) -> QPointF:
        pos = node_item.scenePos()
        return QPointF(
            pos.x() + HuffmanNodeItem.width / 2,
            pos.y() + HuffmanNodeItem.height / 2,
        )