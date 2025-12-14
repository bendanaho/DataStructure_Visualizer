import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple


class HuffmanModel:
    """负责解析输入、维护森林状态，并按步骤提供排序与合并操作。"""

    @dataclass
    class HuffmanNode:
        node_id: int
        weight: float
        symbol: Optional[str] = None
        left: Optional["HuffmanModel.HuffmanNode"] = None
        right: Optional["HuffmanModel.HuffmanNode"] = None

        def is_leaf(self) -> bool:
            return self.left is None and self.right is None

    STAGE_IDLE = "idle"
    STAGE_SORTING = "sorting"
    STAGE_BUILDING = "building"
    STAGE_COMPLETE = "complete"

    def __init__(self):
        self.reset()

    # ---------- Public API ----------

    def reset(self):
        self.forest: List[HuffmanModel.HuffmanNode] = []
        self.stage = self.STAGE_IDLE
        self._next_id = 1
        self._sort_pass = 0
        self._sort_index = 0

    def initialize(self, text: str):
        values = self._parse_sequence(text)
        if not values:
            raise ValueError("请输入至少一个有效的权重。")

        self.reset()
        self.forest = [
            self._make_leaf(symbol, weight) for symbol, weight in values
        ]
        if len(self.forest) <= 1:
            self.stage = self.STAGE_COMPLETE
        else:
            self.stage = self.STAGE_SORTING

    def load_snapshot(self, snapshot: Dict):
        """根据保存的快照重建模型状态。"""
        if not isinstance(snapshot, dict):
            raise ValueError("快照数据必须是字典。")

        required = {"stage", "roots", "nodes"}
        if not required.issubset(snapshot.keys()):
            missing = required - snapshot.keys()
            raise ValueError(f"快照缺少必要字段：{missing}")

        nodes_payload = snapshot.get("nodes") or []
        roots_payload = snapshot.get("roots") or []
        stage_payload = snapshot.get("stage", self.STAGE_IDLE)

        # 允许的阶段
        valid_stages = {
            self.STAGE_IDLE,
            self.STAGE_SORTING,
            self.STAGE_BUILDING,
            self.STAGE_COMPLETE,
        }
        if stage_payload not in valid_stages:
            stage_payload = self.STAGE_IDLE

        # 清空当前状态
        self.reset()

        if not nodes_payload:
            self.stage = self.STAGE_IDLE
            return

        # 第一次遍历：创建节点对象（暂不连接子节点）
        node_objects: Dict[int, HuffmanModel.HuffmanNode] = {}
        for info in nodes_payload:
            node_id = info.get("id")
            weight = info.get("weight")
            if node_id is None or weight is None:
                raise ValueError("快照节点缺少 id 或 weight。")
            try:
                weight = float(weight)
            except (TypeError, ValueError):
                raise ValueError(f"节点 {node_id} 的 weight 无法转换为数字。") from None

            symbol = self._recover_symbol(info)
            node_objects[node_id] = self.HuffmanNode(
                node_id=node_id,
                weight=weight,
                symbol=symbol,
            )

        # 第二次遍历：补全左右子节点引用
        for info in nodes_payload:
            node_id = info["id"]
            node = node_objects[node_id]
            left_id = info.get("left")
            right_id = info.get("right")
            if left_id is not None:
                node.left = node_objects.get(left_id)
            if right_id is not None:
                node.right = node_objects.get(right_id)

        # 构造森林
        forest_nodes: List[HuffmanModel.HuffmanNode] = []
        for root_id in roots_payload:
            root_node = node_objects.get(root_id)
            if root_node:
                forest_nodes.append(root_node)

        if not forest_nodes:
            # 若 roots 缺失，则自动寻找所有未被作为子节点引用的节点作为根
            child_ids = set()
            for info in nodes_payload:
                if info.get("left") is not None:
                    child_ids.add(info["left"])
                if info.get("right") is not None:
                    child_ids.add(info["right"])
            inferred_roots = [
                node for node_id, node in node_objects.items()
                if node_id not in child_ids
            ]
            if not inferred_roots:
                raise ValueError("无法在快照中推断根节点。")
            forest_nodes = sorted(inferred_roots, key=lambda n: n.node_id)

        self.forest = forest_nodes

        # 更新阶段
        if len(self.forest) == 0:
            self.stage = self.STAGE_IDLE
        elif len(self.forest) == 1 and stage_payload == self.STAGE_COMPLETE:
            self.stage = self.STAGE_COMPLETE
        else:
            self.stage = stage_payload

        # 恢复自增 ID
        self._next_id = max(node_objects.keys()) + 1
        self._sort_pass = 0
        self._sort_index = 0

    @property
    def has_data(self) -> bool:
        return len(self.forest) > 0

    def is_complete(self) -> bool:
        return self.stage == self.STAGE_COMPLETE and len(self.forest) == 1

    def next_sort_operation(self) -> Optional[Dict[str, int]]:
        if self.stage != self.STAGE_SORTING or len(self.forest) <= 1:
            if self.stage == self.STAGE_SORTING:
                self.stage = self.STAGE_BUILDING
            return None

        n = len(self.forest)
        while self._sort_pass < n - 1:
            if self._sort_index >= n - self._sort_pass - 1:
                self._sort_pass += 1
                self._sort_index = 0
                continue

            i = self._sort_index
            j = i + 1
            self._sort_index += 1

            if self.forest[i].weight > self.forest[j].weight:
                self.forest[i], self.forest[j] = self.forest[j], self.forest[i]
                return {"i": i, "j": j}

        self.stage = self.STAGE_BUILDING
        return None

    def perform_merge(self) -> Optional[Dict[str, int]]:
        if len(self.forest) < 2:
            if len(self.forest) == 1:
                self.stage = self.STAGE_COMPLETE
            return None

        left = self.forest.pop(0)
        right = self.forest.pop(0)
        parent_weight = left.weight + right.weight
        parent = self._make_parent(parent_weight, left, right)

        inserted = False
        for idx, node in enumerate(self.forest):
            if parent.weight <= node.weight:
                self.forest.insert(idx, parent)
                inserted = True
                break
        if not inserted:
            self.forest.append(parent)

        if len(self.forest) == 1:
            self.stage = self.STAGE_COMPLETE
        else:
            self.stage = self.STAGE_BUILDING

        return {
            "left_id": left.node_id,
            "right_id": right.node_id,
            "parent_id": parent.node_id,
        }

    def snapshot(self) -> Dict:
        nodes: List[Dict] = []
        seen: set = set()
        for root in self.forest:
            self._collect_nodes(root, nodes, seen)

        return {
            "stage": self.stage,
            "roots": [root.node_id for root in self.forest],
            "nodes": nodes,
        }

    # ---------- Helpers ----------

    def _make_leaf(self, symbol: Optional[str], weight: float) -> "HuffmanNode":
        node = self.HuffmanNode(
            node_id=self._next_id,
            weight=weight,
            symbol=symbol.strip() if symbol else None,
        )
        self._next_id += 1
        return node

    def _make_parent(
        self,
        weight: float,
        left: "HuffmanModel.HuffmanNode",
        right: "HuffmanModel.HuffmanNode",
    ) -> "HuffmanNode":
        node = self.HuffmanNode(
            node_id=self._next_id,
            weight=weight,
            left=left,
            right=right,
        )
        self._next_id += 1
        return node

    def _collect_nodes(
        self,
        root: "HuffmanModel.HuffmanNode",
        store: List[Dict],
        visited: set,
    ):
        stack = [root]
        while stack:
            node = stack.pop()
            if node.node_id in visited:
                continue
            visited.add(node.node_id)
            store.append(
                {
                    "id": node.node_id,
                    "weight": node.weight,
                    "label": self._format_node_label(node),
                    "is_leaf": node.is_leaf(),
                    "left": node.left.node_id if node.left else None,
                    "right": node.right.node_id if node.right else None,
                }
            )
            if node.right:
                stack.append(node.right)
            if node.left:
                stack.append(node.left)

    def _format_node_label(self, node: "HuffmanNode") -> str:
        weight_str = self._format_weight(node.weight)
        return f"{node.symbol}:{weight_str}" if node.symbol else weight_str

    @staticmethod
    def _format_weight(value: float) -> str:
        if isinstance(value, int):
            return str(value)
        if isinstance(value, float) and value.is_integer():
            return str(int(value))
        return str(value)

    def _parse_sequence(self, text: str) -> List[Tuple[Optional[str], float]]:
        if not text:
            return []
        normalized = text.replace("，", ",")
        tokens = [
            token.strip()
            for token in re.split(r"[,\s]+", normalized)
            if token.strip()
        ]
        result: List[Tuple[Optional[str], float]] = []
        for token in tokens:
            symbol = None
            value_part = token
            if ":" in token:
                left, right = token.split(":", 1)
                symbol = left.strip() or None
                value_part = right.strip()
            weight = self._coerce_number(value_part)
            result.append((symbol, weight))
        return result

    @staticmethod
    def _coerce_number(raw: str) -> float:
        try:
            return int(raw, 10)
        except ValueError:
            pass
        try:
            return float(raw)
        except ValueError:
            raise ValueError(f"无法解析权重：{raw}")

    @staticmethod
    def _recover_symbol(info: Dict) -> Optional[str]:
        """根据快照信息推断叶子节点的符号（若存在）。"""
        label = info.get("label") or ""
        is_leaf = bool(info.get("is_leaf"))
        if not is_leaf:
            return None
        if ":" not in label:
            return None
        symbol_part, _ = label.split(":", 1)
        symbol_part = symbol_part.strip()
        return symbol_part or None