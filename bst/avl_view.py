from typing import Dict, List, Optional

from PyQt5.QtCore import QPointF, Qt, pyqtSignal
from PyQt5.QtWidgets import QGraphicsItem, QMenu

from bst.bst_view import BSTView, BSTNodeItem


class AVLView(BSTView):
    _child_horizontal_gap = BSTNodeItem.width + 90
    _child_vertical_gap = 130

    def animate_insert(self, snapshot, inserted_id, path_ids):
        positions = self._compute_layout(snapshot)
        if not positions:
            return

        prev_snapshot = self._last_snapshot or {"root": None, "nodes": []}
        current_tree = {node["id"]: node for node in prev_snapshot.get("nodes", [])}
        current_root_id = prev_snapshot.get("root")

        new_info = self._node_info(snapshot, inserted_id)
        final_target = positions.get(inserted_id, QPointF(0.0, 0.0))

        duplicate_target_item = self.node_items.get(inserted_id)
        duplicate_attempt = duplicate_target_item is not None
        temp_insert_placeholder = None

        node_item = duplicate_target_item
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
            if not node_item:
                node_item = self._create_node_item(new_info["id"], new_info["value"])

        if not duplicate_attempt and current_root_id is None:
            spawn = QPointF(final_target.x(), final_target.y() - 160)
            node_item.setPos(spawn)
            node_item.setOpacity(0.0)
            drop = self.anim.move_item(node_item, final_target, duration=840)
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
            spawn = QPointF(final_target.x(), final_target.y() - 160)
            node_item.setPos(spawn)
            node_item.setOpacity(0.0)
            drop = self.anim.move_item(node_item, final_target, duration=840)
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
            spawn = QPointF(final_target.x(), final_target.y() - 160)

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
                child_item = None

            highlight_center = None
            if not child_item:
                if step["is_final"]:
                    highlight_center = self._center_from_position(final_target)
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
                        fallback_pos = final_target
                    move_target = self._stage_position(stage_base_item, fallback_pos)
                    if move_target is None:
                        move_target = fallback_pos or final_target
                    sequence.addAnimation(self.anim.move_item(node_item, move_target, duration=780))
                    overlap_pos = stage_base_item.pos() if stage_base_item else final_target
                    sequence.addAnimation(self.anim.move_item(node_item, overlap_pos, duration=420))
                    continue

                move_target = self._pre_rotation_leaf_target(parent_item, step["direction"], final_target)
                duration = 780
            else:
                fallback_pos = positions.get(child_id)
                move_target = self._stage_position(child_item, fallback_pos)
                if move_target is None:
                    move_target = fallback_pos or (child_item.pos() if child_item else final_target)
                duration = 630

            sequence.addAnimation(self.anim.move_item(node_item, move_target, duration=duration))

        relayout = None if duplicate_attempt else self._animate_relayout(snapshot, positions)
        if relayout:
            sequence.addAnimation(relayout)

        def _finalize():
            if temp_insert_placeholder and temp_insert_placeholder.scene():
                self.scene.removeItem(temp_insert_placeholder)
            self._finalize_insert_animation(snapshot, positions, temp_highlights)

        self._track_animation(sequence, finalizer=_finalize)

    def _finalize_snapshot(self, snapshot, positions, removed_id=None):
        super()._finalize_snapshot(snapshot, positions, removed_id)
        self._update_balance_tooltips(snapshot)

    def _update_balance_tooltips(self, snapshot):
        nodes = snapshot.get("nodes", [])
        if not nodes:
            return
        height_map: Dict[int, int] = {info["id"]: info.get("height", 1) for info in nodes}
        for info in nodes:
            node_item = self.node_items.get(info["id"])
            if not node_item:
                continue
            left_id = info.get("left")
            right_id = info.get("right")
            left_h = height_map.get(left_id, 0) if left_id is not None else 0
            right_h = height_map.get(right_id, 0) if right_id is not None else 0
            tooltip = (
                f"值: {info['value']}\n"
                f"高度: {height_map.get(info['id'], 1)}\n"
                f"平衡因子: {left_h - right_h}"
            )
            node_item.setToolTip(tooltip)

    def _pre_rotation_leaf_target(
        self,
        parent_item: Optional["BSTNodeItem"],
        direction: str,
        fallback: Optional[QPointF] = None,
    ) -> QPointF:
        if not parent_item:
            return fallback if fallback is not None else QPointF(0.0, 0.0)

        parent_center_x = parent_item.pos().x() + BSTNodeItem.width / 2
        parent_top_y = parent_item.pos().y()
        horizontal = self._child_horizontal_gap
        vertical = self._child_vertical_gap

        if direction == "left":
            child_center_x = parent_center_x - horizontal
        elif direction == "right":
            child_center_x = parent_center_x + horizontal
        else:
            return fallback if fallback is not None else QPointF(0.0, 0.0)

        child_x = child_center_x - BSTNodeItem.width / 2
        child_y = parent_top_y + vertical
        return QPointF(child_x, child_y)


class AVLViewWithPersistence(AVLView):
    clearAllRequested = pyqtSignal()
    saveRequested = pyqtSignal()
    loadRequested = pyqtSignal()

    def _show_background_menu(self, screen_pos):
        if isinstance(screen_pos, QPointF):
            screen_pos = screen_pos.toPoint()

        menu = QMenu()
        open_action = menu.addAction("Open From File…")
        save_action = menu.addAction("Save To File…")
        menu.addSeparator()
        clear_action = menu.addAction("Clear Tree")
        chosen = menu.exec_(screen_pos)

        if chosen == open_action:
            self.loadRequested.emit()
        elif chosen == save_action:
            self.saveRequested.emit()
        elif chosen == clear_action:
            self.stop_all_animations()
            self.clearAllRequested.emit()