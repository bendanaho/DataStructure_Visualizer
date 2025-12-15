from typing import Any, Dict, List


class ArrayModel:
    """
    简单的顺序表数据模型，使用字典追踪节点 id，方便视图做增量动画。
    由于不允许使用 append/insert 等内建方法，所有结构变更都通过手动拷贝实现。
    """

    def __init__(self):
        self._next_id = 0
        self._items: List[Dict[str, Any]] = []

    @property
    def length(self) -> int:
        return len(self._items)

    def clear(self):
        self._items = []
        self._next_id = 0

    def _new_cell(self, value):
        cell = {"id": self._next_id, "value": value}
        self._next_id += 1
        return cell

    def _grow_with_element(self, index: int, element: Dict[str, Any]) -> None:
        old_items = self._items
        old_len = len(old_items)
        new_len = old_len + 1
        new_storage: List[Dict[str, Any]] = [None] * new_len  # type: ignore
        for i in range(index):
            new_storage[i] = old_items[i]
        new_storage[index] = element
        for i in range(index, old_len):
            new_storage[i + 1] = old_items[i]
        self._items = new_storage

    def _shrink_without_index(self, index: int) -> None:
        old_items = self._items
        old_len = len(old_items)
        new_len = old_len - 1
        if new_len <= 0:
            self._items = []
            return
        new_storage: List[Dict[str, Any]] = [None] * new_len  # type: ignore
        for i in range(index):
            new_storage[i] = old_items[i]
        for i in range(index + 1, old_len):
            new_storage[i - 1] = old_items[i]
        self._items = new_storage

    def create_from_iterable(self, values):
        self.clear()
        for value in values:
            self.append(value)

    def append(self, value):
        cell = self._new_cell(value)
        self._grow_with_element(self.length, cell)
        return cell["id"]

    def insert(self, index: int, value):
        if index < 0 or index > self.length:
            raise IndexError("Index out of range")
        cell = self._new_cell(value)
        self._grow_with_element(index, cell)
        return cell["id"]

    def delete(self, index: int):
        if index < 0 or index >= self.length:
            raise IndexError("Index out of range")
        removed = self._items[index]
        self._shrink_without_index(index)
        return removed

    def update_value(self, index: int, value):
        if index < 0 or index >= self.length:
            raise IndexError("Index out of range")
        self._items[index]["value"] = value
        return self._items[index]["id"]

    def snapshot(self):
        size = self.length
        result: List[Dict[str, Any]] = [None] * size  # type: ignore
        for i in range(size):
            cell = self._items[i]
            result[i] = {"id": cell["id"], "value": cell["value"]}
        return result

    def load_snapshot(self, snapshot):
        self.clear()
        items = snapshot or []
        count = len(items)
        if count == 0:
            return
        rebuilt: List[Dict[str, Any]] = [None] * count  # type: ignore
        max_id = -1
        for i in range(count):
            cell = items[i]
            node_id = int(cell["id"])
            rebuilt[i] = {"id": node_id, "value": cell["value"]}
            if node_id > max_id:
                max_id = node_id
        self._items = rebuilt
        self._next_id = max_id + 1