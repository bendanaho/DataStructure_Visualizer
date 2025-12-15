import itertools
from typing import Dict, Iterable, List, Optional, Tuple


class DoublyLinkedListModel:
    """
    纯数据层的双向链表模型，每个节点以 dict 存储：
    {
        "id": int,
        "value": Any,
        "prev": Optional[int],
        "next": Optional[int],
    }
    """

    def __init__(self):
        self._id_iter = itertools.count()
        self.head: Optional[int] = None
        self.tail: Optional[int] = None
        self.nodes: Dict[int, Dict] = {}
        self.length = 0

    def _new_node(self, value) -> Tuple[int, Dict]:
        node_id = next(self._id_iter)
        return node_id, {"id": node_id, "value": value, "prev": None, "next": None}

    def clear(self) -> None:
        self.head = None
        self.tail = None
        self.nodes.clear()
        self.length = 0

    def create_from_iterable(self, values: Iterable) -> None:
        self.clear()
        prev_id = None
        for value in values:
            node_id, node = self._new_node(value)
            node["prev"] = prev_id
            if prev_id is not None:
                self.nodes[prev_id]["next"] = node_id
            else:
                self.head = node_id
            self.nodes[node_id] = node
            prev_id = node_id
            self.length += 1
        self.tail = prev_id

    def snapshot(self, include_links: bool = True) -> List[Dict]:
        ordered: List[Dict] = []
        current = self.head
        while current is not None:
            node = self.nodes[current]
            record = {"id": node["id"], "value": node["value"]}
            if include_links:
                record["prev"] = node["prev"]
                record["next"] = node["next"]
            ordered.append(record)
            current = node["next"]
        return ordered

    def insert(self, index: int, value) -> int:
        if index < 0 or index > self.length:
            raise IndexError("Index out of range")

        node_id, node = self._new_node(value)

        if self.length == 0:  # 首个节点
            self.head = self.tail = node_id
        elif index == 0:  # 头插
            node["next"] = self.head
            node["prev"] = None
            self.nodes[self.head]["prev"] = node_id
            self.head = node_id
        elif index == self.length:  # 尾插
            node["prev"] = self.tail
            node["next"] = None
            self.nodes[self.tail]["next"] = node_id
            self.tail = node_id
        else:  # 中间插入
            next_id = self._node_id_at(index)
            prev_id = self.nodes[next_id]["prev"]
            node["prev"] = prev_id
            node["next"] = next_id
            self.nodes[next_id]["prev"] = node_id
            if prev_id is not None:
                self.nodes[prev_id]["next"] = node_id
        self.nodes[node_id] = node
        self.length += 1
        if self.length == 1:
            self.tail = node_id
        return node_id

    def delete(self, index: int) -> Dict:
        if index < 0 or index >= self.length:
            raise IndexError("Index out of range")

        target_id = self._node_id_at(index)
        target = self.nodes[target_id]
        prev_id = target["prev"]
        next_id = target["next"]

        if prev_id is None:
            self.head = next_id
        else:
            self.nodes[prev_id]["next"] = next_id

        if next_id is None:
            self.tail = prev_id
        else:
            self.nodes[next_id]["prev"] = prev_id

        removed = self.nodes.pop(target_id)
        self.length -= 1
        if self.length == 0:
            self.head = self.tail = None
        return removed

    def update_value(self, index: int, value) -> None:
        node_id = self._node_id_at(index)
        self.nodes[node_id]["value"] = value

    def _node_id_at(self, index: int) -> int:
        if index < 0 or index >= self.length:
            raise IndexError("Index out of range")
        current = self.head
        for _ in range(index):
            current = self.nodes[current]["next"]
        return current