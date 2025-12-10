import math
from typing import Dict, List, Optional, Set

from PyQt5.QtCore import QEvent, QPointF, QRectF, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QBrush, QPen, QPainterPath
from PyQt5.QtWidgets import (
    QGraphicsItem,
    QGraphicsObject,
    QGraphicsPathItem,
    QMenu,
    QMessageBox,
)

from core.base_view import BaseStructureView


class BSTView(BaseStructureView):
    deleteRequested = pyqtSignal(int)
    findRequested = pyqtSignal(int)

    def __init__(self, global_ctrl):
        super().__init__(global_ctrl)
        self.scene.installEventFilter(self)

        self.node_items: Dict[int, BSTNodeItem] = {}
        self.edge_items: Dict[tuple, BSTEdgeItem] = {}
        self._last_snapshot = {"root": None, "nodes": []}
        self._temp_insert_counter = 0

    # ---------- Public API ----------

    def reset(self):
        self.stop_all_animations()
        self.scene.clear()
        self.node_items.clear()
        self.edge_items.clear()
        self._last_snapshot = {"root": None, "nodes": []}

    def animate_build(self, snapshot):
        self.reset()
        if not snapshot["nodes"]:
            return

        positions = self._compute_layout(snapshot)
        level_order = self._level_order(snapshot)
        sequential = self.anim.sequential()

        for node_id in level_order:
            info = self._node_info(snapshot, node_id)
            node_item = self._create_node_item(info["id"], info["value"])
            target = positions[node_id]
            spawn = QPointF(target.x(), target.y() - 160)
            node_item.setPos(spawn)
            node_item.setOpacity(0.0)

            drop = self.anim.move_item(node_item, target, duration=560)
            fade = self.anim.fade_item(node_item, 0.0, 1.0, duration=560)
            sequential.addAnimation(self.anim.parallel(drop, fade))

        sequential.addAnimation(self.anim.pause(140))
        self._track_animation(
            sequential,
            finalizer=lambda: self._finalize_snapshot(snapshot, positions),
        )

    def animate_insert(self, snapshot, inserted_id, path_ids):
        positions = self._compute_layout(snapshot)
        if not positions:
            return

        prev_snapshot = self._last_snapshot or {"root": None, "nodes": []}
        current_tree = {node["id"]: node for node in prev_snapshot.get("nodes", [])}
        current_root_id = prev_snapshot.get("root")

        new_info = self._node_info(snapshot, inserted_id)
        target = positions.get(inserted_id, QPointF(0.0, 0.0))

        duplicate_target_item = self.node_items.get(inserted_id)
        duplicate_attempt = duplicate_target_item is not None
        temp_insert_placeholder = None

        if duplicate_attempt:
            self._temp_insert_counter += 1
            temp_id = -self._temp_insert_counter
            node_item = BSTNodeItem(temp_id, new_info["value"])
            node_item.setFlag(QGraphicsItem.ItemIsSelectable, False)
            node_item.setAcceptedMouseButtons(Qt.NoButton)
            node_item.setZValue(3)
            self.scene.addItem(node_item)
            temp_insert_placeholder = node_item
        else:
            node_item = duplicate_target_item
            if not node_item:
                node_item = self._create_node_item(new_info["id"], new_info["value"])

        if not duplicate_attempt and current_root_id is None:
            spawn = QPointF(target.x(), target.y() - 160)
            node_item.setPos(spawn)
            node_item.setOpacity(0.0)
            drop = self.anim.move_item(node_item, target, duration=840)
            fade = self.anim.fade_item(node_item, 0.0, 1.0, duration=840)
            sequence = self.anim.sequential()
            sequence.addAnimation(self.anim.parallel(drop, fade))
            self._track_animation(
                sequence,
                finalizer=lambda: self._finalize_snapshot(snapshot, positions),
            )
            return

        steps = self._build_insert_steps(
            current_tree,
            current_root_id,
            inserted_id,
            new_info["value"],
            path_ids or [],
        )
        if not steps:
            spawn = QPointF(target.x(), target.y() - 160)
            node_item.setPos(spawn)
            node_item.setOpacity(0.0)
            drop = self.anim.move_item(node_item, target, duration=840)
            fade = self.anim.fade_item(node_item, 0.0, 1.0, duration=840)
            sequence = self.anim.sequential()
            sequence.addAnimation(self.anim.parallel(drop, fade))
            self._track_animation(
                sequence,
                finalizer=lambda: self._finalize_snapshot(snapshot, positions),
            )
            return

        horizontal_gap = BSTNodeItem.width + 30
        root_for_spawn_id = snapshot.get("root")
        spawn_base_item = self.node_items.get(root_for_spawn_id)

        if spawn_base_item:
            spawn = QPointF(
                spawn_base_item.pos().x() + horizontal_gap,
                spawn_base_item.pos().y(),
            )
        else:
            spawn = QPointF(target.x(), target.y() - 160)

        node_item.setPos(spawn)
        node_item.setOpacity(0.0)

        temp_highlights: List["EdgeFlashItem"] = []
        sequence = self.anim.sequential()
        sequence.addAnimation(self.anim.fade_item(node_item, 0.0, 1.0, duration=300))

        for step in steps:
            parent_item = self.node_items.get(step["parent"])
            if not parent_item:
                continue

            child_id = step["child"]
            child_item = self.node_items.get(child_id) if child_id is not None else None

            is_new_leaf_step = (
                not duplicate_attempt
                and step["is_final"]
                and child_id == inserted_id
            )
            if is_new_leaf_step:
                child_item = None  # 确保高亮连线指向最终位置

            highlight_center = None
            if not child_item:
                if step["is_final"]:
                    highlight_center = self._center_from_position(target)
                else:
                    child_pos = positions.get(child_id)
                    highlight_center = self._center_from_position(child_pos)

            flash_anim = self._edge_flash_animation(parent_item, child_item, highlight_center, temp_highlights)
            if flash_anim:
                sequence.addAnimation(flash_anim)

            if step["is_final"]:
                if duplicate_attempt:
                    stage_base_item = self.node_items.get(child_id) or duplicate_target_item
                    fallback_pos = positions.get(child_id) if child_id is not None else None
                    if fallback_pos is None:
                        fallback_pos = target
                    move_target = self._stage_position(stage_base_item, fallback_pos)
                    if move_target is None:
                        move_target = fallback_pos or target
                    sequence.addAnimation(self.anim.move_item(node_item, move_target, duration=780))
                    overlap_pos = stage_base_item.pos() if stage_base_item else target
                    sequence.addAnimation(self.anim.move_item(node_item, overlap_pos, duration=420))
                    continue
                move_target = target
                duration = 780
            else:
                fallback_pos = positions.get(child_id)
                move_target = self._stage_position(child_item, fallback_pos)
                if move_target is None:
                    move_target = fallback_pos or (child_item.pos() if child_item else target)
                duration = 630

            sequence.addAnimation(self.anim.move_item(node_item, move_target, duration=duration))

        relayout = None if duplicate_attempt else self._animate_relayout(snapshot, positions, skip_ids={inserted_id})
        if relayout:
            sequence.addAnimation(relayout)

        def _finalize():
            if temp_insert_placeholder and temp_insert_placeholder.scene():
                self.scene.removeItem(temp_insert_placeholder)
            self._finalize_insert_animation(snapshot, positions, temp_highlights)

        self._track_animation(sequence, finalizer=_finalize)

    def animate_delete(self, snapshot, removed_id, path_ids):
        target = self.node_items.get(removed_id)
        if removed_id is None or target is None:
            # 视图缺少目标节点，直接重建
            self._finalize_snapshot(snapshot, self._compute_layout(snapshot))
            return

        new_positions = self._compute_layout(snapshot)
        restore_colors: List[tuple] = []
        traversal = self._build_path_flash(path_ids, restore_colors)
        flash = self.anim.flash_brush(
            setter=target.setFillColor,
            start_color=target.fillColor,
            end_color=QColor("#ff7043"),
            duration=360,
            loops=2,
        )
        lift = self.anim.move_item(
            target,
            target.pos() + QPointF(0, -150),
            duration=420,
        )
        fade = self.anim.fade_item(target, 1.0, 0.0, duration=420)
        relayout = self._animate_relayout(snapshot, new_positions, skip_ids=set())

        sequence = self.anim.sequential()
        if traversal:
            sequence.addAnimation(traversal)
        sequence.addAnimation(flash)
        sequence.addAnimation(self.anim.parallel(lift, fade))
        if relayout:
            sequence.addAnimation(relayout)

        self._track_animation(
            sequence,
            finalizer=lambda: self._finalize_delete(snapshot, new_positions, removed_id, restore_colors),
        )

    def animate_find(self, snapshot, found_id, path_ids):
        positions = self._compute_layout(snapshot)
        sequence = self.anim.sequential()

        duration_scale = 1.0 / 0.8  # 放慢动画速度至原来的 0.8 倍

        restore_colors: List[tuple] = []
        traversal_ids = list(path_ids or [])
        if found_id is not None and traversal_ids and traversal_ids[-1] == found_id:
            traversal_ids = traversal_ids[:-1]

        traversal = self._build_path_flash(traversal_ids, restore_colors, duration_scale)
        if traversal:
            sequence.addAnimation(traversal)

        if found_id is not None and found_id in self.node_items:
            target = self.node_items[found_id]
            original_color = QColor(target.fillColor)
            restore_colors.append((target, original_color))
            flash = self.anim.flash_brush(
                setter=target.setFillColor,
                start_color=original_color,
                end_color=QColor("#ff5252"),
                duration=int(420 * duration_scale),
                loops=2,
            )
            sequence.addAnimation(flash)

        self._track_animation(
            sequence,
            finalizer=lambda: self._finalize_find(snapshot, positions, found_id, restore_colors),
        )

    # ---------- Internal helpers ----------

    def _show_not_found_message(self):
        parent = self._canvas.window() if self._canvas else None
        box = QMessageBox(parent)
        box.setIcon(QMessageBox.Information)
        box.setWindowTitle("查找结果")
        box.setText("<span style='color:#000000;'>未找到目标值。</span>")
        box.setStandardButtons(QMessageBox.Ok)
        ok_button = box.button(QMessageBox.Ok)
        ok_button.setStyleSheet(
            "QPushButton { background-color: #b0bec5; color: #000000; padding: 6px 16px; border-radius: 4px; }"
            "QPushButton:pressed { background-color: #9ea7ac; }"
        )
        box.exec_()

    def _finalize_find(self, snapshot, positions, found_id, restore_colors):
        for item, color in restore_colors:
            if item and item.scene():
                item.setFillColor(color)
        if found_id is None:
            self._show_not_found_message()
        self._finalize_snapshot(snapshot, positions)

    def _create_node_item(self, node_id, value):
        node_item = BSTNodeItem(node_id, value)
        node_item.contextDelete.connect(self.deleteRequested.emit)
        node_item.contextFind.connect(self.findRequested.emit)
        self.scene.addItem(node_item)
        self.node_items[node_id] = node_item
        return node_item

    def _compute_layout(self, snapshot):
        """
        使用基于子树宽度的布局算法，确保：
        1. 父节点始终位于其所有子节点的水平中心
        2. 左子树完全在父节点左侧，右子树完全在父节点右侧
        3. 不会出现连线向内凹的情况
        """
        root_id = snapshot.get("root")
        if root_id is None:
            return {}

        tree = {node["id"]: node for node in snapshot["nodes"]}
        positions: Dict[int, QPointF] = {}

        h_gap = 90  # 相邻节点之间的最小水平间距（增大以使连线角度更大）
        v_gap = 130  # 垂直层级间距（减小以使连线角度更大）
        node_width = BSTNodeItem.width
        min_horizontal_offset = 60  # 单子节点时的最小水平偏移量

        # 第一步：计算每个子树的宽度（以节点数量为基础）
        subtree_width: Dict[int, float] = {}

        def compute_width(node_id: Optional[int]) -> float:
            if node_id is None:
                return 0
            node = tree.get(node_id)
            if node is None:
                return 0

            left_width = compute_width(node["left"])
            right_width = compute_width(node["right"])

            # 子树宽度 = 左子树宽度 + 右子树宽度 + 节点本身占用的空间
            if left_width == 0 and right_width == 0:
                width = node_width
            else:
                width = left_width + right_width
                if left_width > 0 and right_width > 0:
                    width += h_gap
                elif left_width == 0 and right_width > 0:
                    width = max(node_width / 2 + min_horizontal_offset, right_width + node_width / 2 + h_gap / 2)
                elif right_width == 0 and left_width > 0:
                    width = max(node_width / 2 + min_horizontal_offset, left_width + node_width / 2 + h_gap / 2)

            subtree_width[node_id] = width
            return width

        compute_width(root_id)

        # 第二步：根据子树宽度分配位置
        def assign_positions(node_id: Optional[int], x_center: float, depth: int):
            if node_id is None:
                return
            node = tree.get(node_id)
            if node is None:
                return

            y = depth * v_gap
            positions[node_id] = QPointF(x_center - node_width / 2, y)

            left_id = node["left"]
            right_id = node["right"]
            left_w = subtree_width.get(left_id, 0) if left_id else 0
            right_w = subtree_width.get(right_id, 0) if right_id else 0

            if left_id is not None and right_id is not None:
                # 两个子节点都存在
                left_center = x_center - h_gap / 2 - left_w / 2
                right_center = x_center + h_gap / 2 + right_w / 2
                assign_positions(left_id, left_center, depth + 1)
                assign_positions(right_id, right_center, depth + 1)
            elif left_id is not None:
                # 只有左子节点：使用较大的水平偏移
                left_center = x_center - min_horizontal_offset
                assign_positions(left_id, left_center, depth + 1)
            elif right_id is not None:
                # 只有右子节点：使用较大的水平偏移
                right_center = x_center + min_horizontal_offset
                assign_positions(right_id, right_center, depth + 1)

        assign_positions(root_id, 0, 0)

        # 第三步：调整垂直偏移
        if positions:
            min_y = min(p.y() for p in positions.values())
            for node_id in positions:
                positions[node_id] = QPointF(
                    positions[node_id].x(),
                    positions[node_id].y() - min_y - 40
                )

        return positions

    def _level_order(self, snapshot):
        root_id = snapshot.get("root")
        if root_id is None:
            return []
        tree = {node["id"]: node for node in snapshot["nodes"]}
        queue = [root_id]
        order = []
        while queue:
            node_id = queue.pop(0)
            order.append(node_id)
            node = tree[node_id]
            if node["left"] is not None:
                queue.append(node["left"])
            if node["right"] is not None:
                queue.append(node["right"])
        return order

    def _node_info(self, snapshot, node_id):
        for node in snapshot["nodes"]:
            if node["id"] == node_id:
                return node
        raise KeyError(node_id)

    def _build_path_flash(
        self,
        path_ids: List[int],
        restore_store: Optional[List[tuple]] = None,
        duration_scale: float = 1.0,
    ):
        if not path_ids:
            return None
        duration = int(240 * duration_scale)
        seq = self.anim.sequential()
        for node_id in path_ids:
            item = self.node_items.get(node_id)
            if not item:
                continue
            original_color = QColor(item.fillColor)
            if restore_store is not None:
                restore_store.append((item, original_color))
            flash = self.anim.flash_brush(
                setter=item.setFillColor,
                start_color=original_color,
                end_color=QColor("#4fc3f7"),
                duration=duration,
                loops=1,
            )
            seq.addAnimation(flash)
        return seq

    def _animate_relayout(self, snapshot, positions, skip_ids: Optional[Set[int]] = None):
        if not positions:
            return None
        skip_ids = skip_ids or set()
        motions = []
        for node_id, item in self.node_items.items():
            if node_id in skip_ids or node_id not in positions:
                continue
            target = positions[node_id]
            motions.append(self.anim.move_item(item, target, duration=480))
        if not motions:
            return None
        return self.anim.parallel(*motions)

    def _finalize_snapshot(self, snapshot, positions, removed_id=None):
        keep_ids = {node["id"] for node in snapshot["nodes"]}
        if removed_id and removed_id in self.node_items:
            item = self.node_items.pop(removed_id)
            if item.scene():
                self.scene.removeItem(item)

        for node_id in list(self.node_items.keys()):
            if node_id not in keep_ids:
                item = self.node_items.pop(node_id)
                if item.scene():
                    self.scene.removeItem(item)

        for info in snapshot["nodes"]:
            node_item = self.node_items.get(info["id"])
            if not node_item:
                node_item = self._create_node_item(info["id"], info["value"])
                node_item.setOpacity(1.0)
            node_item.set_value(info["value"])
            if positions and info["id"] in positions:
                node_item.setPos(positions[info["id"]])

        self._last_snapshot = snapshot
        self._rebuild_edges(snapshot)
        self._auto_scale_view()
        self._ensure_small_tree_centered()

    def _ensure_small_tree_centered(self):
        if not self._canvas or len(self.node_items) == 0 or len(self.node_items) > 2:
            return

        bounds = self.scene.itemsBoundingRect()
        if bounds.isNull():
            return

        margin = 150
        rect = bounds.adjusted(-margin, -margin, margin, margin)

        min_size = 320
        if rect.width() < min_size:
            center_x = rect.center().x()
            half_w = min_size / 2
            rect.setLeft(center_x - half_w)
            rect.setRight(center_x + half_w)
        if rect.height() < min_size:
            center_y = rect.center().y()
            half_h = min_size / 2
            rect.setTop(center_y - half_h)
            rect.setBottom(center_y + half_h)

        self.scene.setSceneRect(rect)
        self._canvas.centerOn(rect.center())

    def _finalize_delete(self, snapshot, positions, removed_id, restore_colors):
        for item, color in restore_colors:
            if item and item.scene():
                item.setFillColor(color)
        self._finalize_snapshot(snapshot, positions, removed_id)

    def _rebuild_edges(self, snapshot):
        for edge in list(self.edge_items.values()):
            self.scene.removeItem(edge)
        self.edge_items.clear()

        for info in snapshot["nodes"]:
            parent_id = info["id"]
            for child_key in ("left", "right"):
                child_id = info[child_key]
                if child_id is None:
                    continue
                parent_item = self.node_items.get(parent_id)
                child_item = self.node_items.get(child_id)
                if not parent_item or not child_item:
                    continue
                edge = BSTEdgeItem(parent_item, child_item)
                edge.setZValue(0)
                self.scene.addItem(edge)
                self.edge_items[(parent_id, child_id)] = edge

    def _derive_insert_path(self, tree, root_id, inserted_id, inserted_value, fallback_path):
        if not root_id or root_id not in tree:
            return []
        path = []
        current_id = root_id
        safety = 0
        max_steps = len(tree) + 2
        while current_id and current_id != inserted_id and safety < max_steps:
            path.append(current_id)
            node = tree[current_id]
            go_left = self._should_go_left(inserted_value, node["value"])
            next_id = node["left"] if go_left else node["right"]
            if next_id is None:
                break
            current_id = next_id
            safety += 1
        if current_id != inserted_id:
            cleaned = [nid for nid in fallback_path if nid in tree and nid != inserted_id]
            return cleaned
        return path

    @staticmethod
    def _should_go_left(value, parent_value):
        try:
            return value < parent_value
        except TypeError:
            return str(value) < str(parent_value)

    def _stage_position(
        self,
        child_item: Optional["BSTNodeItem"],
        fallback_pos: Optional[QPointF] = None,
    ):
        base_pos = child_item.pos() if child_item else fallback_pos
        if base_pos is None:
            return None
        gap = BSTNodeItem.width + 26
        return QPointF(base_pos.x() + gap, base_pos.y())

    def _build_insert_steps(self, tree, root_id, inserted_id, inserted_value, path_ids):
        if root_id is None or root_id not in tree:
            return []

        original_path = path_ids or []
        sanitized_path = [nid for nid in original_path if nid in tree and nid != inserted_id]

        if not sanitized_path:
            derived = self._derive_insert_path(
                tree,
                root_id,
                inserted_id,
                inserted_value,
                original_path,
            )
            sanitized_path = derived or [root_id]
        if sanitized_path[0] != root_id:
            sanitized_path.insert(0, root_id)

        steps = []
        for idx in range(len(sanitized_path) - 1):
            parent_id = sanitized_path[idx]
            child_id = sanitized_path[idx + 1]
            parent = tree.get(parent_id)
            if not parent or child_id not in tree:
                continue
            direction = "left" if parent["left"] == child_id else "right"
            steps.append(
                {
                    "parent": parent_id,
                    "direction": direction,
                    "child": child_id,
                    "is_final": False,
                }
            )

        final_parent_id = sanitized_path[-1] if sanitized_path else root_id
        parent = tree.get(final_parent_id)
        if not parent:
            return steps

        if parent["value"] == inserted_value:
            steps.append(
                {
                    "parent": final_parent_id,
                    "direction": "duplicate",
                    "child": inserted_id,
                    "is_final": True,
                }
            )
            return steps

        go_left = self._should_go_left(inserted_value, parent["value"])
        direction = "left" if go_left else "right"
        child_id = parent.get(direction)
        if child_id is None:
            child_id = inserted_id

        steps.append(
            {
                "parent": final_parent_id,
                "direction": direction,
                "child": child_id,
                "is_final": True,
            }
        )
        return steps

    def _edge_flash_animation(
        self,
        parent_item: Optional["BSTNodeItem"],
        child_item: Optional["BSTNodeItem"],
        target_center: Optional[QPointF],
        storage: List["EdgeFlashItem"],
    ):
        highlight = self._create_temp_edge_item(parent_item, child_item, target_center)
        if not highlight:
            return None
        storage.append(highlight)
        seq = self.anim.sequential()
        seq.addAnimation(self.anim.fade_item(highlight, 0.0, 1.0, duration=240))
        seq.addAnimation(self.anim.fade_item(highlight, 1.0, 0.0, duration=240))
        return seq

    def _create_temp_edge_item(
        self,
        parent_item: Optional["BSTNodeItem"],
        child_item: Optional["BSTNodeItem"],
        target_center: Optional[QPointF],
    ):
        if not parent_item:
            return None
        start = self._node_center(parent_item)

        if child_item:
            end = self._node_center(child_item)
        elif target_center:
            end = target_center
        else:
            return None

        direction = end - start
        length = math.hypot(direction.x(), direction.y())
        if length < 1e-3:
            return None

        inset = BSTNodeItem.width / 2
        ux = direction.x() / length
        uy = direction.y() / length
        start_point = start + QPointF(ux * inset, uy * inset)
        end_point = end - QPointF(ux * inset, uy * inset)

        local_end = QPointF(end_point.x() - start_point.x(), end_point.y() - start_point.y())
        path = QPainterPath(QPointF(0.0, 0.0))
        path.lineTo(local_end)

        item = EdgeFlashItem(path)
        item.setPos(start_point)
        self.scene.addItem(item)
        return item

    @staticmethod
    def _node_center(node_item: "BSTNodeItem"):
        pos = node_item.pos()
        return QPointF(
            pos.x() + BSTNodeItem.width / 2,
            pos.y() + BSTNodeItem.height / 2,
        )

    @staticmethod
    def _center_from_position(position: Optional[QPointF]):
        if not position:
            return QPointF(0.0, 0.0)
        return QPointF(
            position.x() + BSTNodeItem.width / 2,
            position.y() + BSTNodeItem.height / 2,
        )

    def _finalize_insert_animation(self, snapshot, positions, temp_items):
        for item in temp_items:
            if item and item.scene():
                self.scene.removeItem(item)
        self._finalize_snapshot(snapshot, positions)

    def _show_background_menu(self, screen_pos):
        if isinstance(screen_pos, QPointF):
            screen_pos = screen_pos.toPoint()
        menu = QMenu()
        clear_action = menu.addAction("Clear Tree")
        chosen = menu.exec_(screen_pos)
        if chosen == clear_action:
            self.stop_all_animations()
            for node in list(self.node_items.values()):
                self.scene.removeItem(node)
            for edge in list(self.edge_items.values()):
                self.scene.removeItem(edge)
            self.node_items.clear()
            self.edge_items.clear()

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


class BSTNodeItem(QGraphicsObject):
    contextDelete = pyqtSignal(int)
    contextFind = pyqtSignal(int)
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
        self.setFlag(QGraphicsItem.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.ItemSendsGeometryChanges, True)

    def boundingRect(self):
        return QRectF(0, 0, self.width, self.height)

    def paint(self, painter, option, widget=None):
        painter.setRenderHint(painter.Antialiasing)
        painter.setPen(QPen(self.strokeColor, 2))
        painter.setBrush(QBrush(self.fillColor))
        painter.drawEllipse(self.boundingRect())

        painter.setPen(self.textColor)
        painter.setFont(painter.font())
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

    def contextMenuEvent(self, event):
        menu = QMenu()
        delete_action = menu.addAction("Delete Node")
        find_action = menu.addAction("Find Node")
        chosen = menu.exec_(event.screenPos())
        if chosen == delete_action:
            self.contextDelete.emit(self.node_id)
        elif chosen == find_action:
            self.contextFind.emit(self.node_id)

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionHasChanged:
            self.positionChanged.emit()
        return super().itemChange(change, value)


class BSTEdgeItem(QGraphicsPathItem):
    def __init__(self, parent_item: BSTNodeItem, child_item: BSTNodeItem):
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
        offset = BSTNodeItem.width / 2

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
    def _center(node_item: BSTNodeItem):
        pos = node_item.scenePos()
        return QPointF(
            pos.x() + BSTNodeItem.width / 2,
            pos.y() + BSTNodeItem.height / 2,
        )


class EdgeFlashItem(QGraphicsObject):
    def __init__(self, path: QPainterPath):
        super().__init__()
        self._path = QPainterPath(path)
        self._pen = QPen(QColor("#ff4d4d"), 5)
        self._pen.setCapStyle(Qt.RoundCap)
        self._pen.setJoinStyle(Qt.RoundJoin)
        self.setOpacity(0.0)
        self.setZValue(1.5)
        self.setAcceptedMouseButtons(Qt.NoButton)

    def boundingRect(self):
        return self._path.boundingRect()

    def paint(self, painter, option, widget=None):
        painter.setRenderHint(painter.Antialiasing)
        painter.setPen(self._pen)
        painter.drawPath(self._path)