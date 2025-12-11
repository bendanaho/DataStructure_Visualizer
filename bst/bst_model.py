import itertools
from typing import Any, Dict, List, Optional, Tuple


class BSTModel:
    """
    简单的二叉搜索树数据模型，节点使用唯一 id，方便视图做增量动画。
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

        rebuilt = {}
        max_id = -1
        for info in nodes:
            node_id = info["id"]
            rebuilt[node_id] = {
                "id": node_id,
                "value": info["value"],
                "left": info["left"],
                "right": info["right"],
            }
            max_id = max(max_id, node_id)

        self._nodes = rebuilt
        self._root = root if root in rebuilt or root is None else None
        self._id_iter = itertools.count(max_id + 1 if max_id >= 0 else 0)

    def create_from_iterable(self, values):
        self.clear()
        for value in values:
            self.insert(value)

    def insert(self, value) -> Tuple[int, List[int]]:
        """
        返回 (新节点 id, 搜索路径 id 列表)。
        搜索路径只包含已有节点，用于动画展示。
        若值已存在，则不插入新节点，直接返回已存在节点的 id 与路径。
        """
        path: List[int] = []

        if self._root is None:
            new_node = self._make_node(value)
            self._root = new_node["id"]
            return new_node["id"], path

        current_id = self._root
        parent_id = None
        direction = None

        while current_id is not None:
            parent_id = current_id
            path.append(current_id)
            current = self._nodes[current_id]
            if value == current["value"]:
                return current_id, path
            if value < current["value"]:
                direction = "left"
                current_id = current["left"]
            else:
                direction = "right"
                current_id = current["right"]

        new_node = self._make_node(value)
        if parent_id is None:
            self._root = new_node["id"]
        else:
            self._nodes[parent_id][direction] = new_node["id"]

        return new_node["id"], path

    def delete(self, value) -> Tuple[Optional[int], List[int]]:
        """
        返回 (被删除节点 id，搜索路径)；若未找到则 id 为 None。
        """
        path: List[int] = []
        parent_id = None
        current_id = self._root
        direction = None

        while current_id is not None:
            path.append(current_id)
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
        else:
            return None, path

        node = self._nodes[current_id]

        # 0 or 1 child
        if node["left"] is None or node["right"] is None:
            replacement = node["left"] if node["left"] is not None else node["right"]
            self._replace_child(parent_id, current_id, replacement, direction)
        else:
            # 2 children → 找右子树最左节点
            succ_parent = current_id
            succ_id = node["right"]
            path.append(succ_id)
            while self._nodes[succ_id]["left"] is not None:
                succ_parent = succ_id
                succ_id = self._nodes[succ_id]["left"]
                path.append(succ_id)

            successor = self._nodes[succ_id]

            # 将后继节点从原位置摘下
            if succ_parent != current_id:
                self._nodes[succ_parent]["left"] = successor["right"]
                successor["right"] = node["right"]
            successor["left"] = node["left"]

            self._replace_child(parent_id, current_id, succ_id, direction)
            if succ_parent == current_id:
                # 原目标节点的右子就是后继，需要避免自引用
                # successor["right"] 已经等于 node["right"]，无需额外处理
                pass

        # 删除节点
        del self._nodes[current_id]
        if current_id == self._root:
            # 根节点更新逻辑在 _replace_child 中完成
            pass

        return current_id, path

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
                }
                for node_id, node in self._nodes.items()
            ],
        }

    def value_of(self, node_id: int):
        node = self._nodes.get(node_id)
        return node["value"] if node else None

    # ---------- Internal helpers ----------

    def _make_node(self, value):
        node_id = next(self._id_iter)
        node = {"id": node_id, "value": value, "left": None, "right": None}
        self._nodes[node_id] = node
        return node

    def _replace_child(self, parent_id, old_child_id, new_child_id, direction=None):
        if parent_id is None:
            self._root = new_child_id
        else:
            if direction is None:
                direction = (
                    "left"
                    if self._nodes[parent_id]["left"] == old_child_id
                    else "right"
                )
            self._nodes[parent_id][direction] = new_child_id