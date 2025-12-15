from typing import Dict, List, Optional


class StackModel:
    """Simple stack backed by manual list manipulation without append/pop."""

    def __init__(self):
        self._next_id = 0
        self._items: List[Dict] = []

    def _grow_with(self, info: Dict) -> None:
        old_items = self._items
        old_len = len(old_items)
        new_storage: List[Optional[Dict]] = [None] * (old_len + 1)
        for i in range(old_len):
            new_storage[i] = old_items[i]
        new_storage[old_len] = info
        self._items = new_storage  # type: ignore

    def _shrink(self) -> Dict:
        old_items = self._items
        old_len = len(old_items)
        if old_len == 0:
            raise IndexError("Stack empty")
        removed = old_items[old_len - 1]
        new_len = old_len - 1
        if new_len == 0:
            self._items = []
            return removed
        new_storage: List[Optional[Dict]] = [None] * new_len
        for i in range(new_len):
            new_storage[i] = old_items[i]
        self._items = new_storage  # type: ignore
        return removed

    def snapshot(self) -> List[Dict]:
        size = len(self._items)
        copy_list: List[Optional[Dict]] = [None] * size
        for i in range(size):
            item = self._items[i]
            copy_list[i] = {"id": item["id"], "value": item["value"]}
        return copy_list  # type: ignore

    def push(self, value):
        node_id = self._next_id
        self._next_id += 1
        info = {"id": node_id, "value": value}
        self._grow_with(info)
        return info

    def pop(self):
        return self._shrink()

    def __len__(self):
        return len(self._items)

    def load_snapshot(self, nodes):
        size = len(nodes)
        new_storage: List[Optional[Dict]] = [None] * size
        max_id = -1
        for i in range(size):
            item = nodes[i]
            cell = {"id": item["id"], "value": item["value"]}
            new_storage[i] = cell
            if item["id"] > max_id:
                max_id = item["id"]
        self._items = new_storage  # type: ignore
        self._next_id = max_id + 1 if max_id >= 0 else 0