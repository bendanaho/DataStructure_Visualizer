import itertools
from typing import Any, Dict, List, Optional, Tuple


class AVLModel:
    """
    平衡二叉搜索树（AVL）数据模型，节点使用唯一 id，方便视图做增量动画。
    """

    def __init__(self):
        self._id_iter = itertools.count()
        self._nodes: Dict[int, Dict[str, Any]] = {}
        self._root: Optional[int] = None

    @property
    def length(self) -> int:
        return len(self._nodes)

    def clear(self):
        self._nodes.clear()
        self._root = None
        self._id_iter = itertools.count()

    def load_snapshot(self, snapshot):
        self.clear()
        nodes = snapshot.get("nodes", [])
        root = snapshot.get("root")

        rebuilt: Dict[int, Dict[str, Any]] = {}
        max_id = -1
        for info in nodes:
            node_id = info["id"]
            rebuilt[node_id] = {
                "id": node_id,
                "value": info["value"],
                "left": info["left"],
                "right": info["right"],
                "height": info.get("height", 1),
            }
            max_id = max(max_id, node_id)

        self._nodes = rebuilt
        self._root = root if root in rebuilt or root is None else None
        self._id_iter = itertools.count(max_id + 1 if max_id >= 0 else 0)
        self._recalculate_all_heights()

    def create_from_iterable(self, values):
        self.clear
        for value in values:
            self.insert(value)

    def insert(self, value) -> Tuple[int, List[int]]:
        path: List[int] = []
        if self._root is None:
            new_node = self._make_node(value)
            self._root = new_node["id"]
            return new_node["id"], path

        new_root, inserted_id, _ = self._insert_recursive(self._root, value, path)
        self._root = new_root
        return inserted_id, path

    def delete(self, value) -> Tuple[Optional[int], List[int]]:
        path: List[int] = []
        new_root, removed_id, found = self._delete_recursive(self._root, value, path)
        self._root = new_root
        if not found:
            return None, path
        return removed_id, path

    def find(self, value) -> Tuple[Optional[int], List[int]]:
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

    def value_of(self, node_id: int):
        node = self._nodes.get(node_id)
        return node["value"] if node else None

    # ---------- Internal helpers ----------

    def _insert_recursive(
        self,
        node_id: Optional[int],
        value,
        path: List[int],
    ) -> Tuple[int, int, bool]:
        if node_id is None:
            new_node = self._make_node(value)
            return new_node["id"], new_node["id"], True

        node = self._nodes[node_id]
        path.append(node_id)

        if value == node["value"]:
            return node_id, node_id, False

        if value < node["value"]:
            child_id, inserted_id, inserted = self._insert_recursive(node["left"], value, path)
            node["left"] = child_id
        else:
            child_id, inserted_id, inserted = self._insert_recursive(node["right"], value, path)
            node["right"] = child_id

        self._update_height(node_id)
        new_root_id = self._rebalance_node(node_id)
        return new_root_id, inserted_id, inserted

    def _delete_recursive(
        self,
        node_id: Optional[int],
        value,
        path: List[int],
    ) -> Tuple[Optional[int], Optional[int], bool]:
        if node_id is None:
            return None, None, False

        node = self._nodes[node_id]
        path.append(node_id)

        if value < node["value"]:
            new_left, removed_id, found = self._delete_recursive(node["left"], value, path)
            if not found:
                return node_id, None, False
            node["left"] = new_left
        elif value > node["value"]:
            new_right, removed_id, found = self._delete_recursive(node["right"], value, path)
            if not found:
                return node_id, None, False
            node["right"] = new_right
        else:
            removed_id = node_id
            if node["left"] is None:
                replacement = node["right"]
                self._remove_node(node_id)
                return replacement, removed_id, True
            if node["right"] is None:
                replacement = node["left"]
                self._remove_node(node_id)
                return replacement, removed_id, True

            new_right_root, successor_id = self._detach_min(node["right"], path)
            successor = self._nodes[successor_id]
            successor["left"] = node["left"]
            successor["right"] = new_right_root
            self._remove_node(node_id)
            self._update_height(successor_id)
            new_root = self._rebalance_node(successor_id)
            return new_root, removed_id, True

        self._update_height(node_id)
        new_root = self._rebalance_node(node_id)
        return new_root, removed_id, True

    def _detach_min(
        self,
        node_id: int,
        path: List[int],
    ) -> Tuple[Optional[int], int]:
        node = self._nodes[node_id]
        path.append(node_id)
        if node["left"] is None:
            return node["right"], node_id

        new_left, min_id = self._detach_min(node["left"], path)
        node["left"] = new_left
        self._update_height(node_id)
        new_root = self._rebalance_node(node_id)
        return new_root, min_id

    def _make_node(self, value):
        node_id = next(self._id_iter)
        node = {
            "id": node_id,
            "value": value,
            "left": None,
            "right": None,
            "height": 1,
        }
        self._nodes[node_id] = node
        return node

    def _remove_node(self, node_id: int):
        if node_id in self._nodes:
            del self._nodes[node_id]

    def _height(self, node_id: Optional[int]) -> int:
        if node_id is None:
            return 0
        node = self._nodes.get(node_id)
        return node.get("height", 0) if node else 0

    def _update_height(self, node_id: Optional[int]):
        if node_id is None:
            return
        node = self._nodes.get(node_id)
        if not node:
            return
        left_h = self._height(node["left"])
        right_h = self._height(node["right"])
        node["height"] = 1 + max(left_h, right_h)

    def _balance_factor(self, node_id: Optional[int]) -> int:
        if node_id is None:
            return 0
        node = self._nodes.get(node_id)
        if not node:
            return 0
        return self._height(node["left"]) - self._height(node["right"])

    def _rebalance_node(self, node_id: int) -> int:
        balance = self._balance_factor(node_id)
        node = self._nodes[node_id]

        if balance > 1:
            left_id = node["left"]
            if left_id is None:
                return node_id
            if self._balance_factor(left_id) < 0:
                node["left"] = self._rotate_left(left_id)
            return self._rotate_right(node_id)

        if balance < -1:
            right_id = node["right"]
            if right_id is None:
                return node_id
            if self._balance_factor(right_id) > 0:
                node["right"] = self._rotate_right(right_id)
            return self._rotate_left(node_id)

        return node_id

    def _rotate_left(self, z_id: int) -> int:
        z = self._nodes[z_id]
        y_id = z["right"]
        if y_id is None:
            return z_id
        y = self._nodes[y_id]
        t2 = y["left"]

        y["left"] = z_id
        z["right"] = t2

        self._update_height(z_id)
        self._update_height(y_id)
        return y_id

    def _rotate_right(self, z_id: int) -> int:
        z = self._nodes[z_id]
        y_id = z["left"]
        if y_id is None:
            return z_id
        y = self._nodes[y_id]
        t3 = y["right"]

        y["right"] = z_id
        z["left"] = t3

        self._update_height(z_id)
        self._update_height(y_id)
        return y_id

    def _recalculate_all_heights(self):
        def compute(node_id: Optional[int]) -> int:
            if node_id is None or node_id not in self._nodes:
                return 0
            node = self._nodes[node_id]
            left_h = compute(node["left"])
            right_h = compute(node["right"])
            node["height"] = 1 + max(left_h, right_h)
            return node["height"]

        compute(self._root)