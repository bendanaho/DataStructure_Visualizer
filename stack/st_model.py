import itertools
from typing import Dict, List


class StackModel:
    """Simple stack backed by Python list but with explicit element ids."""

    def __init__(self):
        self._id_iter = itertools.count()
        self._items: List[Dict] = []

    def snapshot(self):
        return list(self._items)

    def push(self, value):
        node_id = next(self._id_iter)
        info = {"id": node_id, "value": value}
        self._items.append(info)
        return info

    def pop(self):
        if not self._items:
            raise IndexError("Stack empty")
        return self._items.pop()

    def __len__(self):
        return len(self._items)