import itertools
from typing import Dict, List, Optional


class LinkedListModel:
    """
    Singly linked list model implemented with dictionaries to keep the model
    side purely data-driven (no Qt objects).
    """

    def __init__(self):
        self._id_iter = itertools.count()
        self.head: Optional[int] = None
        self.nodes: Dict[int, Dict] = {}
        self.length = 0

    def _new_node(self, value):
        node_id = next(self._id_iter)
        return node_id, {"id": node_id, "value": value, "next": None}

    def clear(self):
        self.head = None
        self.nodes.clear()
        self.length = 0

    def create_from_iterable(self, values):
        self.clear()
        prev_id = None
        for value in values:
            node_id, node = self._new_node(value)
            self.nodes[node_id] = node
            if self.head is None:
                self.head = node_id
            if prev_id is not None:
                self.nodes[prev_id]["next"] = node_id
            prev_id = node_id
            self.length += 1

    def snapshot(self) -> List[Dict]:
        ordered = []
        current = self.head
        while current is not None:
            node = self.nodes[current]
            ordered.append({"id": node["id"], "value": node["value"]})
            current = node["next"]
        return ordered

    def insert(self, index: int, value):
        if index < 0 or index > self.length:
            raise IndexError("Index out of range")

        node_id, node = self._new_node(value)

        if index == 0:
            node["next"] = self.head
            self.head = node_id
        else:
            prev_id = self._node_id_at(index - 1)
            node["next"] = self.nodes[prev_id]["next"]
            self.nodes[prev_id]["next"] = node_id

        self.nodes[node_id] = node
        self.length += 1
        return node_id

    def delete(self, index: int) -> Dict:
        if index < 0 or index >= self.length:
            raise IndexError("Index out of range")

        if index == 0:
            removed_id = self.head
            self.head = self.nodes[removed_id]["next"]
        else:
            prev_id = self._node_id_at(index - 1)
            removed_id = self.nodes[prev_id]["next"]
            self.nodes[prev_id]["next"] = self.nodes[removed_id]["next"]

        removed = self.nodes.pop(removed_id)
        self.length -= 1
        return removed

    def update_value(self, index: int, value):
        node_id = self._node_id_at(index)
        self.nodes[node_id]["value"] = value

    def _node_id_at(self, index: int) -> int:
        if index < 0 or index >= self.length:
            raise IndexError("Index out of range")
        current = self.head
        for _ in range(index):
            current = self.nodes[current]["next"]
        return current