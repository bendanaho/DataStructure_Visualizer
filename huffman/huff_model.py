import heapq
import itertools
from typing import Any, Dict, List, Tuple


class HuffmanModel:
    """
    生成哈夫曼树构建全过程所需的初始序列、排序步骤、合并步骤及最终树结构。
    """

    def __init__(self):
        self._id_iter = itertools.count()

    def build_process(self, raw_values: List[float]) -> Dict[str, Any]:
        cleaned: List[float] = []
        for value in raw_values:
            val = float(value)
            if val > 0:
                cleaned.append(val)

        if not cleaned:
            return {
                "initial": [],
                "sorting": [],
                "building": [],
                "final_tree": {"root": None, "nodes": []},
            }

        leaf_nodes = [
            {"id": next(self._id_iter), "value": val, "left": None, "right": None}
            for val in cleaned
        ]

        initial_state = [node.copy() for node in leaf_nodes]
        sorting_steps, sorted_nodes = self._insertion_sort_steps([node.copy() for node in leaf_nodes])
        build_steps, final_snapshot = self._build_steps(sorted_nodes)

        return {
            "initial": initial_state,
            "sorting": sorting_steps,
            "building": build_steps,
            "final_tree": final_snapshot,
        }

    # ---------- 排序阶段 ----------

    def _insertion_sort_steps(self, nodes: List[Dict[str, Any]]):
        steps: List[Dict[str, Any]] = []
        if not nodes:
            return steps, []

        arr: List[Dict[str, Any]] = list(nodes)
        for i in range(1, len(arr)):
            key = arr[i]
            j = i - 1
            while j >= 0 and arr[j]["value"] > key["value"]:
                j -= 1
            insert_index = j + 1
            if insert_index == i:
                continue
            steps.append(
                {
                    "array_before": [node["id"] for node in arr],
                    "key_id": key["id"],
                    "from_index": i,
                    "insert_index": insert_index,
                }
            )
            arr.pop(i)
            arr.insert(insert_index, key)

        sorted_nodes = [node.copy() for node in arr]
        return steps, sorted_nodes

    # ---------- 构建阶段 ----------

    def _build_steps(self, nodes: List[Dict[str, Any]]):
        if not nodes:
            return [], {"root": None, "nodes": []}

        heap: List[Tuple[float, int, Dict[str, Any]]] = []
        node_map: Dict[int, Dict[str, Any]] = {}
        for node in nodes:
            data = {
                "id": node["id"],
                "value": node["value"],
                "left": node.get("left"),
                "right": node.get("right"),
            }
            node_map[data["id"]] = data
            heapq.heappush(heap, (data["value"], data["id"], data))

        if len(heap) == 1:
            root_id = heap[0][1]
            return [], self._build_snapshot(root_id, node_map)

        steps: List[Dict[str, Any]] = []
        while len(heap) >= 2:
            left_val, _, left_node = heapq.heappop(heap)
            right_val, _, right_node = heapq.heappop(heap)

            parent_id = next(self._id_iter)
            parent_node = {
                "id": parent_id,
                "value": left_val + right_val,
                "left": left_node["id"],
                "right": right_node["id"],
            }
            node_map[parent_id] = parent_node
            heapq.heappush(heap, (parent_node["value"], parent_id, parent_node))

            steps.append(
                {
                    "left_id": left_node["id"],
                    "right_id": right_node["id"],
                    "parent": parent_node.copy(),
                }
            )

        root_id = heap[0][1]
        return steps, self._build_snapshot(root_id, node_map)

    @staticmethod
    def _build_snapshot(root_id: int, node_map: Dict[int, Dict[str, Any]]):
        return {
            "root": root_id,
            "nodes": [
                {
                    "id": node_id,
                    "value": data["value"],
                    "left": data["left"],
                    "right": data["right"],
                }
                for node_id, data in node_map.items()
            ],
        }