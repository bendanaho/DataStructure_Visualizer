import itertools
from typing import Any, Dict, List, Optional

from bst.bst_model import BSTModel


class AVLModel(BSTModel):
    """
    带有旋转中间状态采集能力的 AVL 数据模型。
    insert/delete 均返回包含快照序列的结果，供视图逐帧播放。
    """

    def __init__(self):
        super().__init__()

    # ---------- 对外 API ----------

    def insert(self, value):
        steps = [self._step("before_insert", {"value": value})]
        # 模拟查找过程
        existing_id, path = self._trace_path(value) # 如果树中已经存在这个 value，返回该节点的 ID；否则返回 None。
        if existing_id is not None:# 重复值
            steps.append(   # 记录一帧“发现重复”的快照
                self._step("duplicate", {"node_id": existing_id, "path": list(path)})
            )
            return {        # 立即结束函数。返回状态为 "duplicate"
                "status": "duplicate",
                "node_id": existing_id,
                "path": list(path),
                "steps": steps,
            }

        inserted_id = self._bst_insert_with_path(value, path)# 此时树的结构已经改变，但尚未进行平衡检查，树可能已经失衡
        steps.append(       # 记录一帧“物理插入完成”的快照
            self._step(
                "after_bst_insert",
                {
                    "inserted": inserted_id,
                    "path": path + [inserted_id],
                },
            )
        )

        self._rebalance_upwards(    # 从这个新插入的节点开始，沿着父指针向上查
            start_ids=[inserted_id],
            steps=steps,
            cause="insert",
            stop_after_first=True,
        )

        steps.append(               # 记录最终状态
            self._step(
                "after_insert",
                {
                    "inserted": inserted_id,
                },
            )
        )

        return {
            "status": "inserted",
            "node_id": inserted_id,
            "path": path + [inserted_id],
            "steps": steps,#  包含了从“插入前” -> “物理插入” -> “旋转中” -> “旋转后” -> “最终状态”的所有快照序列
        }

    def delete(self, value):
        steps = [self._step("before_delete", {"value": value})]

        target_id, path = self._trace_path(value)
        if target_id is None or target_id not in self._nodes:
            steps.append(self._step("not_found", {"path": list(path)}))
            return {
                "status": "not_found",
                "deleted_id": None,
                "path": list(path),
                "steps": steps,
            }

        removed_id, rebalance_starts = self._bst_delete(value, path)
        steps.append(
            self._step(
                "after_structural_delete",
                {"deleted": removed_id, "path": list(path)},
            )
        )

        self._rebalance_upwards(
            start_ids=rebalance_starts,
            steps=steps,
            cause="delete",
            stop_after_first=False,
        )

        steps.append(
            self._step(
                "after_delete",
                {"deleted": removed_id},
            )
        )

        return {
            "status": "deleted",
            "deleted_id": removed_id,
            "path": list(path),
            "steps": steps,
        }

    def snapshot(self) -> Dict[str, Any]:
        return {
            "root": self._root,
            "nodes": [
                {
                    "id": node_id,
                    "value": node["value"],
                    "left": node["left"],
                    "right": node["right"],
                    "height": node.get("height", 1),
                }
                for node_id, node in self._nodes.items()
            ],
        }

    def load_snapshot(self, snapshot):
        super().load_snapshot(snapshot)
        for node in self._nodes.values():
            node["height"] = node.get("height", 1)
        self._recompute_heights()

    # ---------- BST 基础操作扩展 ----------

    def _make_node(self, value):
        node = super()._make_node(value)
        node["height"] = 1
        return node

    def _bst_insert_with_path(self, value, path: List[int]) -> int:
        if self._root is None:
            new_node = self._make_node(value)
            self._root = new_node["id"]
            return new_node["id"]

        parent_id = path[-1] if path else None
        new_node = self._make_node(value)
        if parent_id is None:
            self._root = new_node["id"]
            return new_node["id"]

        parent = self._nodes[parent_id]
        if value < parent["value"]:
            parent["left"] = new_node["id"]
        else:
            parent["right"] = new_node["id"]
        return new_node["id"]

    def _bst_delete(self, value, path_ref: List[int]):
        parent_id = None
        current_id = self._root
        direction = None

        while current_id is not None:
            node = self._nodes[current_id]
            if value == node["value"]:
                break
            parent_id = current_id
            if value < node["value"]:
                direction = "left"
                current_id = node["left"]
            else:
                direction = "right"
                current_id = node["right"]
            path_ref.append(parent_id)
        else:
            raise RuntimeError("Value should exist before calling _bst_delete")

        node = self._nodes[current_id]
        rebalance_candidates: List[Optional[int]] = []

        # 0 or 1 child
        if node["left"] is None or node["right"] is None:
            replacement = node["left"] if node["left"] is not None else node["right"]
            self._replace_child(parent_id, current_id, replacement, direction)
            del self._nodes[current_id]
            if parent_id is not None:
                rebalance_candidates.append(parent_id)
            elif replacement is not None:
                rebalance_candidates.append(replacement)
            return current_id, self._dedup_chain(rebalance_candidates)

        # 2 children → 找后继
        succ_parent = current_id
        succ_id = node["right"]
        path_ref.append(succ_id)
        while self._nodes[succ_id]["left"] is not None:
            succ_parent = succ_id
            succ_id = self._nodes[succ_id]["left"]
            path_ref.append(succ_id)

        successor = self._nodes[succ_id]
        if succ_parent != current_id:
            self._nodes[succ_parent]["left"] = successor["right"]
            successor["right"] = node["right"]
        successor["left"] = node["left"]

        self._replace_child(parent_id, current_id, succ_id, direction)
        del self._nodes[current_id]

        rebalance_candidates.extend(
            [
                succ_parent if succ_parent != current_id else succ_id,
                parent_id,
                succ_id,
            ]
        )
        return current_id, self._dedup_chain(rebalance_candidates)

    # ---------- Rebalance ----------

    def _rebalance_upwards(self, start_ids, steps, cause, stop_after_first):
        if self._root is None:
            return
        start_chain = self._dedup_chain(start_ids)
        if not start_chain:
            return

        parent_map = self._build_parent_map()
        visited = set()
        # 当插入或删除一个节点后，只有该节点到根节点路径上的祖先节点的高度可能会发生变化，从而导致失衡。
        for start_id in start_chain:
            current = start_id
            while current is not None:
                if current not in self._nodes:
                    current = parent_map.get(current)
                    continue
                if current not in visited:
                    # 1. 更新当前节点的高度
                    # 因为子树变了，当前节点的高度可能需要重新计算（左子树高 vs 右子树高 + 1）
                    self._update_height(current)
                    # 2. 计算平衡因子 (左高 - 右高)
                    balance = self._balance_factor(current)
                    # 3. 判断是否失衡 (绝对值 > 1 说明失衡)
                    if abs(balance) > 1:
                        # 4. 决定怎么旋转
                        rotation = self._plan_rotation(current)
                        parent_id = parent_map.get(current)
                        # 5. 执行旋转
                        new_root = self._execute_rotation(
                            rotation, parent_id, steps, cause
                        )
                        # 6. 旋转后结构变了，必须重建父节点映射，以便继续往上走
                        parent_map = self._build_parent_map()
                        current = parent_map.get(new_root)
                        # 7. 插入操作的特权：修好一个就收工
                        if stop_after_first:
                            return
                        continue    # current已经被设置成了父节点
                    visited.add(current)
                # 继续向上找父亲
                current = parent_map.get(current)

    def _execute_rotation(self, rotation, parent_id, steps, cause):
        meta_base = {"rotation": dict(rotation), "cause": cause}

        steps.append(self._step("rotation_before", {**meta_base, "stage": "before"}))

        pivot_id = rotation["pivot"]
        rotation_type = rotation["type"]

        if rotation_type == "LL":
            new_root = self._rotate_right(pivot_id)
        elif rotation_type == "RR":
            new_root = self._rotate_left(pivot_id)
        elif rotation_type == "LR":
            left_child = self._nodes[pivot_id]["left"]
            self._nodes[pivot_id]["left"] = self._rotate_left(left_child)
            steps.append(self._step("rotation_mid", {**meta_base, "stage": "mid"}))
            new_root = self._rotate_right(pivot_id)
        else:  # RL
            right_child = self._nodes[pivot_id]["right"]
            self._nodes[pivot_id]["right"] = self._rotate_right(right_child)
            steps.append(self._step("rotation_mid", {**meta_base, "stage": "mid"}))
            new_root = self._rotate_left(pivot_id)

        self._attach_new_root(parent_id, pivot_id, new_root)
        steps.append(self._step("rotation_after", {**meta_base, "stage": "after"}))
        return new_root

    def _plan_rotation(self, pivot_id):
        balance = self._balance_factor(pivot_id)
        if balance > 1:
            child_id = self._nodes[pivot_id]["left"]    # 获取当前失衡节点（pivot_id）的左子节点的 ID
            child_balance = self._balance_factor(child_id)
            if child_balance >= 0:
                grandchild_id = self._nodes[child_id]["left"]
                rotation_type = "LL"
            else:
                grandchild_id = self._nodes[child_id]["right"]
                rotation_type = "LR"
        else:
            child_id = self._nodes[pivot_id]["right"]
            child_balance = self._balance_factor(child_id)
            if child_balance <= 0:
                grandchild_id = self._nodes[child_id]["right"]
                rotation_type = "RR"
            else:
                grandchild_id = self._nodes[child_id]["left"]
                rotation_type = "RL"

        return {
            "type": rotation_type,
            "pivot": pivot_id,
            "child": child_id,
            "grandchild": grandchild_id,
        }

    def _rotate_left(self, z_id):
        y_id = self._nodes[z_id]["right"]
        if y_id is None:
            return z_id
        y = self._nodes[y_id]
        t2 = y["left"]

        self._nodes[z_id]["right"] = t2
        y["left"] = z_id

        self._update_height(z_id)
        self._update_height(y_id)
        return y_id

    def _rotate_right(self, z_id):
        # z 是失衡点 (旧根)，y 是 z 的左孩子 (新根)
        y_id = self._nodes[z_id]["left"]
        if y_id is None:
            return z_id
        y = self._nodes[y_id]
        t3 = y["right"] # T3 是 y 的右子树，它夹在 y 和 z 之间

        self._nodes[z_id]["left"] = t3
        y["right"] = z_id

        self._update_height(z_id)
        self._update_height(y_id)
        return y_id

    def _attach_new_root(self, parent_id, old_child_id, new_child_id):
        if parent_id is None:
            self._root = new_child_id
            return
        parent = self._nodes[parent_id]
        if parent["left"] == old_child_id:
            parent["left"] = new_child_id
        else:
            parent["right"] = new_child_id

    # ---------- Helpers ----------

    def _trace_path(self, value):
        path: List[int] = []
        current_id = self._root
        while current_id is not None:
            path.append(current_id)
            node = self._nodes[current_id]
            if value == node["value"]:
                return current_id, path
            if value < node["value"]:
                current_id = node["left"]
            else:
                current_id = node["right"]
        return None, path

    def _node_height(self, node_id: Optional[int]) -> int:
        if node_id is None:
            return 0
        node = self._nodes.get(node_id)
        if not node:
            return 0
        return node.get("height", 1)

    def _update_height(self, node_id: Optional[int]):
        if node_id is None or node_id not in self._nodes:
            return
        node = self._nodes[node_id]
        node["height"] = 1 + max(
            self._node_height(node["left"]),
            self._node_height(node["right"]),
        )

    def _balance_factor(self, node_id: Optional[int]) -> int:
        if node_id is None or node_id not in self._nodes:
            return 0
        node = self._nodes[node_id]
        return self._node_height(node["left"]) - self._node_height(node["right"])

    # 遍历全树构建了一个 child_id -> parent_id 的映射表
    def _build_parent_map(self):
        mapping: Dict[int, Optional[int]] = {}

        def dfs(node_id, parent_id):
            if node_id is None:
                return
            mapping[node_id] = parent_id
            node = self._nodes[node_id]
            dfs(node["left"], node_id)
            dfs(node["right"], node_id)

        if self._root is not None:
            dfs(self._root, None)
        return mapping

    def _dedup_chain(self, items):
        seen = set()
        ordered = []
        for item in items:
            if item is None:
                continue
            if item in seen:
                continue
            if item not in self._nodes:
                continue
            ordered.append(item)
            seen.add(item)
        return ordered

    def _recompute_heights(self):
        def dfs(node_id):
            if node_id is None:
                return 0
            node = self._nodes[node_id]
            left_h = dfs(node["left"])
            right_h = dfs(node["right"])
            node["height"] = 1 + max(left_h, right_h)
            return node["height"]

        if self._root is not None:
            dfs(self._root)

    def _step(self, label: str, meta: Optional[Dict[str, Any]] = None):
        return {
            "label": label,
            "snapshot": self.snapshot(),
            "meta": meta or {},
        }