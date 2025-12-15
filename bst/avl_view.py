from typing import Dict, List, Optional, Set

from PyQt5.QtCore import QPointF, pyqtSignal
from PyQt5.QtGui import QColor

from bst.bst_view import BSTNodeItem, BSTView, BSTViewWithPersistence


class AVLView(BSTView):
    """
    支持连续播放中间快照的 AVL 视图。
    """

    def __init__(self, global_ctrl):
        super().__init__(global_ctrl)
        self._pending_steps: Optional[List[Dict]] = None
        self._current_step_index = 0

    # ---------- 新动画入口 ----------

    def animate_operation_steps(self, steps: List[Dict]):
        if not steps:
            return
        self.stop_all_animations()
        self._pending_steps = steps
        self._current_step_index = 0

        first_snapshot = steps[0]["snapshot"]
        first_positions = self._layout_with_bst_style(first_snapshot)
        self._finalize_snapshot(first_snapshot, first_positions)

        if len(steps) == 1:
            self._pending_steps = None
            return

        self._play_next_step()

    def _play_next_step(self):
        if not self._pending_steps:
            return
        if self._current_step_index >= len(self._pending_steps) - 1:
            self._pending_steps = None
            self._current_step_index = 0
            return

        prev_step = self._pending_steps[self._current_step_index]
        next_step = self._pending_steps[self._current_step_index + 1]
        animation, restore_colors = self._build_transition_animation(prev_step, next_step)
        self._current_step_index += 1
        self._track_animation(
            animation,
            finalizer=lambda step=next_step, colors=restore_colors: self._on_step_completed(
                step, colors
            ),
        )

    def _on_step_completed(self, step, restore_colors):
        self._restore_colors(restore_colors)
        snapshot = step["snapshot"]
        positions = self._layout_with_bst_style(snapshot)
        self._finalize_snapshot(snapshot, positions)

        if (
                self._pending_steps
                and self._current_step_index < len(self._pending_steps) - 1
        ):
            self._play_next_step()
        else:
            self._pending_steps = None
            self._current_step_index = 0

    # ---------- Transition 细节 ----------

    def _build_transition_animation(self, prev_step, next_step):
        restore_colors: List[tuple] = []
        sequence = self.anim.sequential()

        highlight = self._build_meta_highlights(next_step.get("meta"), restore_colors)
        if highlight:
            sequence.addAnimation(highlight)

        motion = self._build_move_and_fade(
            prev_step["snapshot"],
            next_step["snapshot"],
        )
        if motion:
            sequence.addAnimation(motion)
        else:
            sequence.addAnimation(self.anim.pause(240))

        return sequence, restore_colors

    def _build_move_and_fade(self, prev_snapshot, next_snapshot):
        prev_positions = self._layout_with_bst_style(prev_snapshot)
        next_positions = self._layout_with_bst_style(next_snapshot)

        # 确保当前画面处于上一帧状态
        self._finalize_snapshot(prev_snapshot, prev_positions)

        next_ids = {info["id"] for info in next_snapshot["nodes"]}
        prev_ids = {info["id"] for info in prev_snapshot["nodes"]}

        motions = []
        new_node_ids: Set[int] = set()

        for info in next_snapshot["nodes"]:
            node_id = info["id"]
            target = next_positions.get(node_id, QPointF(0, 0))
            item = self.node_items.get(node_id)
            if node_id not in prev_ids:
                new_node_ids.add(node_id)
                if not item:
                    item = self._create_node_item(node_id, info["value"])
                spawn = QPointF(target.x(), target.y() - 140)
                item.setPos(spawn)
                item.setOpacity(0.0)
                motions.append(
                    self.anim.parallel(
                        self.anim.move_item(item, target, duration=520),
                        self.anim.fade_item(item, 0.0, 1.0, duration=520),
                    )
                )

        for node_id in prev_ids - next_ids:
            item = self.node_items.get(node_id)
            if not item:
                continue
            motions.append(
                self.anim.parallel(
                    self.anim.move_item(
                        item,
                        item.pos() + QPointF(0, -120),
                        duration=420,
                    ),
                    self.anim.fade_item(item, 1.0, 0.0, duration=420),
                )
            )

        relayout = self._animate_relayout(next_snapshot, next_positions, skip_ids=new_node_ids)
        if relayout:
            motions.append(relayout)

        if not motions:
            return None
        if len(motions) == 1:
            return motions[0]
        return self.anim.parallel(*motions)

    def _build_meta_highlights(self, meta, restore_colors):
        if not meta:
            return None
        sequence = self.anim.sequential()

        path_ids = meta.get("path")
        if path_ids:
            highlight = self._build_path_flash(path_ids, restore_colors, duration_scale=1.2)
            if highlight:
                sequence.addAnimation(highlight)

        rotation = meta.get("rotation")
        if rotation:
            flashes = []
            palette = [QColor("#ff7043"), QColor("#ffd54f"), QColor("#4fc3f7")]
            ids = [
                rotation.get("pivot"),
                rotation.get("child"),
                rotation.get("grandchild"),
            ]
            for idx, node_id in enumerate(ids):
                if node_id is None:
                    continue
                item = self.node_items.get(node_id)
                if not item:
                    continue
                base = QColor(item.fillColor)
                restore_colors.append((item, base))
                flashes.append(
                    self.anim.flash_brush(
                        setter=item.setFillColor,
                        start_color=base,
                        end_color=palette[min(idx, len(palette) - 1)],
                        duration=300,
                        loops=2,
                    )
                )
            if flashes:
                sequence.addAnimation(self.anim.parallel(*flashes))

        return sequence if sequence.animationCount() > 0 else None

    def _restore_colors(self, restore_colors):
        for item, color in restore_colors:
            if item and item.scene():
                item.setFillColor(color)

    def _compute_layout(self, snapshot):
        """
        重写布局计算：
        采用 Reingold-Tilford 算法的简化变体，
        根据树的高度动态计算每一层的水平偏移量 (offset)，
        从而强制实现对称性，避免单侧子树过宽导致根节点偏离中心。
        """
        root_id = snapshot.get("root")
        if root_id is None:
            return {}

        tree = {node["id"]: node for node in snapshot["nodes"]}
        positions: Dict[int, QPointF] = {}

        # 基础参数
        v_gap = 100  # 垂直间距
        node_width = BSTNodeItem.width

        # 1. 计算每个节点的高度（从下往上，叶子为1）
        node_heights: Dict[int, int] = {}

        def get_height(node_id: Optional[int]) -> int:
            if node_id is None:
                return 0
            node = tree.get(node_id)
            if not node:
                return 0
            h = 1 + max(get_height(node["left"]), get_height(node["right"]))
            node_heights[node_id] = h
            return h

        total_height = get_height(root_id)

        # 2. 递归分配位置
        # x_center: 当前子树根节点的中心 X 坐标
        # depth: 当前深度（根为0）
        # available_width: 当前层级预留的宽度范围，用于计算 offset
        def assign_positions(node_id: Optional[int], x_center: float, depth: int):
            if node_id is None:
                return

            node = tree.get(node_id)
            if not node:
                return

            # 设置当前节点坐标
            y = depth * v_gap
            positions[node_id] = QPointF(x_center - node_width / 2, y)

            left_id = node["left"]
            right_id = node["right"]

            # 核心逻辑：根据当前节点的高度计算水平偏移量
            # 越靠近根部，偏移量越大；越靠近叶子，偏移量越小。
            # 2 ** (height - 2) 是一个指数衰减因子，保证上层开阔，下层紧凑。
            current_height = node_heights.get(node_id, 1)

            # 基础偏移量，保证叶子节点之间至少有一定间距
            base_offset = node_width * 0.8

            # 动态偏移量：高度越高，跨度越大
            # 这里的系数 50 可以调整，越大树越宽
            dynamic_offset = base_offset + (2 ** (current_height - 2)) * 50 if current_height > 1 else base_offset

            if left_id is not None:
                assign_positions(left_id, x_center - dynamic_offset, depth + 1)

            if right_id is not None:
                assign_positions(right_id, x_center + dynamic_offset, depth + 1)

        assign_positions(root_id, 0, 0)

        # 3. 整体居中调整（垂直方向）
        if positions:
            min_y = min(p.y() for p in positions.values())
            for node_id in positions:
                positions[node_id] = QPointF(
                    positions[node_id].x(),
                    positions[node_id].y() - min_y - 40
                )

        return positions

    def _layout_with_bst_style(self, snapshot):
        return self._compute_layout(snapshot)


class AVLViewWithPersistence(AVLView):
    clearAllRequested = pyqtSignal()
    saveRequested = pyqtSignal()
    loadRequested = pyqtSignal()
    saveImageRequested = pyqtSignal()  # [新增] 定义保存图片的信号

    def _show_background_menu(self, screen_pos):
        if isinstance(screen_pos, QPointF):
            screen_pos = screen_pos.toPoint()

        from PyQt5.QtWidgets import QMenu

        menu = QMenu()
        open_action = menu.addAction("Open From File…")
        save_action = menu.addAction("Save To File…")
        save_img_action = menu.addAction("Save as Image…")  # [新增] 菜单项
        menu.addSeparator()
        clear_action = menu.addAction("Clear Tree")

        chosen = menu.exec_(screen_pos)
        if chosen == open_action:
            self.loadRequested.emit()
        elif chosen == save_action:
            self.saveRequested.emit()
        elif chosen == save_img_action:
            self.saveImageRequested.emit()  # [新增] 触发信号
        elif chosen == clear_action:
            self.stop_all_animations()
            self.clearAllRequested.emit()