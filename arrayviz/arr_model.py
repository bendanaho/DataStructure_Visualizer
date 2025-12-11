import itertools
from typing import Any, Dict, List


class ArrayModel:
    """
    简单的顺序表数据模型，使用字典追踪节点 id，方便视图做增量动画。
    """

    def __init__(self):
        self._id_iter = itertools.count()
        self._items: List[Dict[str, Any]] = []

    @property
    def length(self) -> int:
        return len(self._items)

    def clear(self):
        self._items.clear()
        self._id_iter = itertools.count()

    def _new_cell(self, value):
        cell_id = next(self._id_iter)
        return {"id": cell_id, "value": value}

    def create_from_iterable(self, values):
        self.clear()
        for value in values:
            self._items.append(self._new_cell(value))

    def append(self, value):
        cell = self._new_cell(value)
        self._items.append(cell)
        return cell["id"]

    def insert(self, index: int, value):
        if index < 0 or index > self.length:
            raise IndexError("Index out of range")
        cell = self._new_cell(value)
        self._items.insert(index, cell)
        return cell["id"]

    def delete(self, index: int):
        if index < 0 or index >= self.length:
            raise IndexError("Index out of range")
        return self._items.pop(index)

    def update_value(self, index: int, value):
        if index < 0 or index >= self.length:
            raise IndexError("Index out of range")
        self._items[index]["value"] = value
        return self._items[index]["id"]

    def snapshot(self):
        return [{"id": cell["id"], "value": cell["value"]} for cell in self._items]

    def load_snapshot(self, snapshot):
        self.clear()
        items = snapshot or []
        rebuilt = []
        max_id = -1
        for cell in items:
            node_id = int(cell["id"])
            rebuilt.append({"id": node_id, "value": cell["value"]})
            max_id = max(max_id, node_id)
        self._items = rebuilt
        self._id_iter = itertools.count(max_id + 1 if max_id >= 0 else 0)