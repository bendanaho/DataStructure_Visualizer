"""core/command_parser.py

提供 DSL 解析与执行能力，用于驱动各个数据结构的控制器。
"""
from __future__ import annotations

import json
import logging
from typing import Any, List, Optional, Tuple, TYPE_CHECKING

from PyQt5.QtCore import QEventLoop, QTimer
from PyQt5.QtWidgets import QApplication
import time
from huffman.huff_model import HuffmanModel

if TYPE_CHECKING:  # 避免运行时循环导入
    from main import MainWindow


DSL_SPEC = """
语法：<STRUCTURE> <ACTION> [ARGS]
  STRUCTURE ∈ {ARRAY, LINKED_LIST, STACK, BST, HUFFMAN, CURRENT}
  | CURRENT 代表当前激活的结构。
  ACTION（大小写不敏感）：
    ARRAY:
      CREATE <list>        # 列表写法示例：[1,2,3] 或 1,2,3
      APPEND <value>
      INSERT <index> <value>
      UPDATE <index> <value>
      DELETE <index>
      CLEAR
    LINKED_LIST:
      CREATE <list>
      APPEND <value>
      INSERT <index> <value>
      UPDATE <index> <value>
      DELETE <index>
      CLEAR
    STACK:
      PUSH <value>
      POP [count]          # count 省略时默认 1
      CLEAR
    BST:
      CREATE <numeric_list>
      INSERT <number>
      DELETE <number>
      FIND <number>
      CLEAR
    HUFFMAN:
      INIT <weights>       # 例如：5,9,12 或 A:5,B:9
      STEP                 # 单步（排序或合并）
      RESET
规则：
  - 每行一条指令，可用分号分隔多条；# 之后视为注释。
  - 值可用引号包裹以保留空格；列表支持 JSON 写法。
  - 输出或执行时不要包含额外说明。
""".strip()


class CommandParserError(Exception):
    """DSL 解析或执行阶段的通用异常。"""


class CommandSyntaxError(CommandParserError):
    """DSL 语法错误。"""


class CommandExecutionError(CommandParserError):
    """执行阶段（模型或视图操作）出现的问题。"""


class CommandParser:
    """解析文本 DSL，并驱动 MainWindow 中对应的控制器。"""
    ANIMATION_TIMEOUT_MS = 2000
    FALLBACK_WAIT_MS = 700            # 信号不可用时的兜底等待
    COOLDOWN_WAIT_MS = 200            # 冷却期，排空事件队列
    BUSY_WAIT_TIMEOUT_MS = 4000       # 轮询等待的总超时时间
    BUSY_POLL_INTERVAL_MS = 30        # 轮询间隔
    def __init__(self, main_window: MainWindow):
        self.main_window = main_window
        # DSL 结构别名 → MainWindow 注册名
        self._structure_aliases = {
            "ARRAY": "Array",
            "ARR": "Array",
            "ARRAYVIZ": "Array",
            "LINKED_LIST": "Linked List",
            "LINKLIST": "Linked List",
            "LL": "Linked List",
            "LIST": "Linked List",
            "STACK": "Stack",
            "BST": "BST",
            "TREE": "BST",
            "HUFFMAN": "Huffman",
            "HUFF": "Huffman",
        }
        self._handlers = {
            "Array": self._handle_array,
            "Linked List": self._handle_linked_list,
            "Stack": self._handle_stack,
            "BST": self._handle_bst,
            "Huffman": self._handle_huffman,
        }

    # ---------- 公共入口 ----------

    def parse_and_execute(self, script: str) -> List[str]:
        """
        解析多条指令并顺序执行，返回每条指令的执行摘要。
        """
        if not script or not script.strip():
            raise CommandSyntaxError("没有可执行的指令。")

        logs: List[str] = []
        for line_no, command in enumerate(self._iter_commands(script), start=1):
            try:
                summary, view = self._dispatch(command)
                logs.append(f"第 {line_no} 行：{summary}")
                self._wait_for_view_settle(view)
            except CommandParserError as exc:
                raise CommandParserError(f"第 {line_no} 行错误：{exc}") from exc
            except IndexError as exc:
                raise CommandExecutionError(
                    "检测到索引越界错误，可能是动画同步延迟导致。"
                    "请尝试在指令之间留出额外间隔或检查动画状态。"
                ) from exc
            except Exception as exc:  # 兜底，便于定位未知错误
                raise CommandExecutionError(
                    f"第 {line_no} 行执行出现异常：{exc}"
                ) from exc
        return logs

    def _wait_for_view_settle(self, view=None):
        """
        使用 View 的 animation_finished 信号精确等待动画结束，
        若信号不可用则退回到轮询，再不行才触发兜底延时，确保指令串行执行。
        """
        if view is None:
            return

        settled = self._wait_via_animation_signal(view)

        if not settled:
            settled = self._wait_by_polling(view)

        if not settled:
            logging.debug(
                "视图 %s 缺少动画完成信号，且轮询超时，触发兜底延时 %d ms。",
                type(view).__name__,
                self.FALLBACK_WAIT_MS,
            )
            self._blocking_delay(self.FALLBACK_WAIT_MS)

        # 冷却期：给 Qt 额外时间处理 residual events
        self._blocking_delay(self.COOLDOWN_WAIT_MS)

    def _wait_via_animation_signal(self, view) -> bool:
        animation_signal = getattr(view, "animation_finished", None)
        if animation_signal is None:
            return False

        connect = getattr(animation_signal, "connect", None)
        disconnect = getattr(animation_signal, "disconnect", None)
        if not callable(connect):
            return False

        loop = QEventLoop()
        timeout_ms = getattr(view, "animation_timeout_ms", self.ANIMATION_TIMEOUT_MS)
        timer = QTimer()
        timer.setSingleShot(True)

        completed = False

        def _on_timeout():
            logging.warning(
                "等待视图 %s 动画完成超时（%d ms），将继续执行后续指令。",
                type(view).__name__,
                timeout_ms,
            )
            loop.quit()

        def _on_finished():
            nonlocal completed
            completed = True
            loop.quit()

        try:
            connect(_on_finished)
        except (TypeError, RuntimeError) as exc:
            logging.warning("连接 animation_finished 信号失败：%s", exc)
            return False

        timer.timeout.connect(_on_timeout)
        timer.start(timeout_ms)
        loop.exec_()

        if timer.isActive():
            timer.stop()

        try:
            timer.timeout.disconnect(_on_timeout)
        except (TypeError, RuntimeError):
            pass

        try:
            if callable(disconnect):
                disconnect(_on_finished)
        except (TypeError, RuntimeError):
            pass

        return completed

    def _wait_by_polling(self, view) -> bool:
        """
        轮询视图的动画运行状态，直到其空闲或超时。
        返回 True 表示动画已完成，False 表示超时或无法检测。
        """
        checker = None

        is_animating = getattr(view, "is_animating", None)
        if callable(is_animating):
            checker = is_animating
        elif hasattr(view, "_running"):
            checker = lambda: bool(getattr(view, "_running"))

        if checker is None:
            return False

        deadline = time.monotonic() + self.BUSY_WAIT_TIMEOUT_MS / 1000.0

        while checker():
            if time.monotonic() >= deadline:
                logging.warning(
                    "轮询等待视图 %s 动画结束超时（%d ms）。",
                    type(view).__name__,
                    self.BUSY_WAIT_TIMEOUT_MS,
                )
                return False
            self._blocking_delay(self.BUSY_POLL_INTERVAL_MS)

        return True

    @staticmethod
    def _blocking_delay(milliseconds: int):
        if milliseconds <= 0:
            return
        loop = QEventLoop()
        QTimer.singleShot(milliseconds, loop.quit)
        loop.exec_()

    # ---------- 指令拆解 ----------

    def _iter_commands(self, script: str):
        for raw in script.splitlines():
            sanitized = self._strip_comments(raw)
            if not sanitized:
                continue
            for fragment in sanitized.split(";"):
                cmd = fragment.strip()
                if cmd:
                    yield cmd

    @staticmethod
    def _strip_comments(line: str) -> str:
        if "#" in line:
            line = line.split("#", 1)[0]
        return line.strip()

    def _dispatch(self, command: str) -> Tuple[str, Any]:
        sanitized = (command or "").strip()
        if not sanitized:
            return "空指令，已跳过。", None

        parts = sanitized.split()
        if not parts:
            return "空指令，已跳过。", None

        first_token = parts[0]
        remainder_tokens = parts[1:]
        remainder = " ".join(remainder_tokens)

        if self._is_structure_token(first_token):
            if not remainder_tokens:
                raise CommandSyntaxError("指令至少包含结构名与动作。")
            action_token = remainder_tokens[0]
            args_str = " ".join(remainder_tokens[1:])
            structure_token = first_token
        else:
            structure_token = self.main_window.active_structure_name
            if not structure_token:
                raise CommandExecutionError("当前没有激活的结构，无法推断指令目标。")
            action_token = first_token
            args_str = remainder

        canonical_name = self._resolve_structure(structure_token)
        handler = self._handlers.get(canonical_name)
        if handler is None:
            raise CommandExecutionError(f"{canonical_name} 暂未开放 DSL 操作。")

        controller = self._controller_for(canonical_name)
        message, view = handler(controller, action_token.upper(), args_str)
        return f"{canonical_name} -> {message}", view

    def _is_structure_token(self, token: str) -> bool:
        if not token:
            return False
        token_up = token.strip().upper()
        if token_up in {"CURRENT", "CUR"}:
            return True
        return token_up in self._structure_aliases

    def _resolve_structure(self, token: str) -> str:
        cleaned = token.strip()
        if not cleaned:
            raise CommandSyntaxError("结构名不能为空。")

        # 1) 已经是正式注册名（如 "Linked List"）
        if cleaned in self._handlers:
            return cleaned

        token_up = cleaned.upper()

        # 2) CURRENT / CUR
        if token_up in {"CURRENT", "CUR"}:
            name = self.main_window.active_structure_name
            if not name:
                raise CommandExecutionError("当前没有激活的结构。")
            return name

        # 3) 别名（ARRAY / LINKED_LIST / ...）
        name = self._structure_aliases.get(token_up)
        if not name:
            raise CommandSyntaxError(f"未知的数据结构标识：{token}")
        return name

    def _controller_for(self, canonical_name: str):
        self.main_window.ensure_structure_active(canonical_name)
        controller = self.main_window.get_controller(canonical_name)
        if controller is None:
            raise CommandExecutionError(f"未找到 {canonical_name} 控制器实例。")
        return controller

    # ---------- Array ----------
    def _handle_array(self, controller, action: str, args: str) -> Tuple[str, Any]:
        model = controller.model
        view = controller.view

        if action == "CREATE":
            values = self._parse_list_argument(args, allow_empty=False)
            model.create_from_iterable(values)
            snapshot = model.snapshot()
            if snapshot:
                view.animate_build(snapshot)
            else:
                view.reset()
            controller._refresh_spins()
            return f"创建长度 {model.length} 的数组。", view

        if action == "APPEND":
            value = self._coerce_value(args.strip())
            index = model.length
            inserted_id = model.insert(index, value)
            snapshot = model.snapshot()
            view.animate_insert(snapshot, inserted_id, index)
            controller._refresh_spins()
            return f"尾部追加元素（索引 {index}）。", view

        if action == "INSERT":
            index, value = self._parse_index_and_value(args)
            if not 0 <= index <= model.length:
                raise CommandExecutionError("插入索引超出范围。")
            inserted_id = model.insert(index, value)
            snapshot = model.snapshot()
            view.animate_insert(snapshot, inserted_id, index)
            controller._refresh_spins()
            return f"在索引 {index} 插入元素。", view

        if action == "UPDATE":
            index, value = self._parse_index_and_value(args)
            if not 0 <= index < model.length:
                raise CommandExecutionError("更新索引超出范围。")
            model.update_value(index, value)
            snapshot = model.snapshot()
            view.animate_update_value(snapshot, index)
            controller._refresh_spins()
            return f"更新索引 {index} 的值。", view

        if action == "DELETE":
            index = self._parse_index_only(args)
            if not 0 <= index < model.length:
                raise CommandExecutionError("删除索引超出范围。")
            snapshot_before = model.snapshot()
            removed_id = snapshot_before[index]["id"]
            model.delete(index)
            snapshot_after = model.snapshot()
            view.animate_delete(snapshot_after, removed_id, index)
            controller._refresh_spins()
            return f"删除索引 {index}。", view

        if action == "CLEAR":
            model.clear()
            view.reset()
            controller._refresh_spins()
            return "数组已清空。", view

        raise CommandSyntaxError(f"Array 不支持动作：{action}")

    # ---------- Linked List ----------

    def _handle_linked_list(self, controller, action: str, args: str) -> Tuple[str, Any]:
        model = controller.model
        view = controller.view

        if action == "CREATE":
            values = self._parse_list_argument(args, allow_empty=False)
            model.create_from_iterable(values)
            snapshot = model.snapshot()
            if snapshot:
                view.animate_build(snapshot)
            else:
                view.reset()
            controller._refresh_spins()
            return f"创建长度 {model.length} 的链表。", view

        if action == "APPEND":
            value = self._coerce_value(args.strip())
            index = model.length
            inserted_id = model.insert(index, value)
            snapshot = model.snapshot()
            view.animate_insert(snapshot, inserted_id, index)
            controller._refresh_spins()
            return "尾插一个节点。", view

        if action == "INSERT":
            index, value = self._parse_index_and_value(args)
            if not 0 <= index <= model.length:
                raise CommandExecutionError("插入索引超出范围。")
            inserted_id = model.insert(index, value)
            snapshot = model.snapshot()
            view.animate_insert(snapshot, inserted_id, index)
            controller._refresh_spins()
            return f"在索引 {index} 插入节点。", view

        if action == "UPDATE":
            index, value = self._parse_index_and_value(args)
            if not 0 <= index < model.length:
                raise CommandExecutionError("更新索引超出范围。")
            model.update_value(index, value)
            view.update_values(model.snapshot())
            controller._refresh_spins()
            return f"更新节点 {index} 的值。", view

        if action == "DELETE":
            index = self._parse_index_only(args)
            if not 0 <= index < model.length:
                raise CommandExecutionError("删除索引超出范围。")
            removed = model.delete(index)
            snapshot = model.snapshot()
            view.animate_delete(snapshot, removed["id"], index)
            controller._refresh_spins()
            return f"删除索引 {index}。", view

        if action == "CLEAR":
            model.clear()
            view.reset()
            controller._refresh_spins()
            return "链表已清空。", view

        raise CommandSyntaxError(f"Linked List 不支持动作：{action}")

    # ---------- Stack ----------

    def _handle_stack(self, controller, action: str, args: str) -> Tuple[str, Any]:
        model = controller.model
        view = controller.view

        if action == "PUSH":
            if not args.strip():
                raise CommandSyntaxError("PUSH 需要一个值。")
            value = controller._coerce_value(args.strip())
            info = model.push(value)
            snapshot = model.snapshot()
            view.animate_push(snapshot, info)
            return "入栈 1 个元素。", view

        if action == "POP":
            count = self._parse_optional_int(args, default=1, min_value=1)
            available = len(model)
            if count > available:
                raise CommandExecutionError(f"栈中仅有 {available} 个元素，无法弹出 {count} 个。")
            for _ in range(count):
                popped = model.pop()
                snapshot = model.snapshot()
                view.animate_pop(snapshot, popped)
            return f"出栈 {count} 个元素。", view

        if action == "CLEAR":
            controller._on_clear_all_requested()
            return "栈已清空。", view

        raise CommandSyntaxError(f"Stack 不支持动作：{action}")

    # ---------- BST ----------

    def _handle_bst(self, controller, action: str, args: str) -> Tuple[str, Any]:
        model = controller.model
        view = controller.view

        if action == "CREATE":
            values = self._parse_list_argument(args, allow_empty=False, require_numeric=True)
            model.create_from_iterable(values)
            snapshot = model.snapshot()
            if snapshot["nodes"]:
                view.animate_build(snapshot)
            else:
                view.reset()
            controller._refresh_inputs()
            return f"创建包含 {len(values)} 个元素的 BST。", view

        if action == "INSERT":
            value = self._coerce_numeric(args.strip())
            inserted_id, path = model.insert(value)
            snapshot = model.snapshot()
            view.animate_insert(snapshot, inserted_id, path)
            controller._refresh_inputs()
            return f"插入节点值 {value}。", view

        if action == "DELETE":
            value = self._coerce_numeric(args.strip())
            removed_id, path = model.delete(value)
            snapshot = model.snapshot()
            if removed_id is None:
                view.animate_find(snapshot, None, path)
                msg = "未找到节点，执行查找高亮。"
            else:
                view.animate_delete(snapshot, removed_id, path)
                msg = f"删除节点值 {value}。"
            controller._refresh_inputs()
            return msg, view

        if action == "FIND":
            value = self._coerce_numeric(args.strip())
            found_id, path = model.find(value)
            snapshot = model.snapshot()
            view.animate_find(snapshot, found_id, path)
            return "查找操作已完成。", view

        if action == "CLEAR":
            model.clear()
            view.reset()
            controller._refresh_inputs()
            return "BST 已清空。", view

        raise CommandSyntaxError(f"BST 不支持动作：{action}")

    # ---------- Huffman ----------

    def _handle_huffman(self, controller, action: str, args: str) -> Tuple[str, Any]:
        model = controller.model
        view = controller.view

        if action == "INIT":
            payload = args.strip()
            if not payload:
                raise CommandSyntaxError("INIT 需要至少一个权重。")
            if payload.startswith("["):
                weights = self._parse_list_argument(payload, allow_empty=False)
                payload = ", ".join(str(w) for w in weights)
            controller.model.initialize(payload)
            snapshot = model.snapshot()
            view.animate_initialize(snapshot)
            controller._update_status()
            controller._refresh_controls()
            return "Huffman 初始化完成。", view

        if action == "STEP":
            progressed, message = self._advance_huffman(controller)
            controller._update_status()
            controller._refresh_controls()
            return f"{'执行一步' if progressed else '无可执行步骤'}：{message}", view

        if action == "RESET":
            model.reset()
            view.reset()
            controller._update_status()
            controller._refresh_controls()
            return "Huffman 状态已重置。", view

        raise CommandSyntaxError(f"Huffman 不支持动作：{action}")

    def _advance_huffman(self, controller) -> Tuple[bool, str]:
        model = controller.model
        view = controller.view

        # 修改说明：将错误的属性名 'has数据' 修正为 'has_data'
        if not getattr(model, "has_data", False):
            raise CommandExecutionError("尚未通过 INIT 初始化数据。")

        stage = model.stage
        if stage == HuffmanModel.STAGE_SORTING:
            steps = []
            while True:
                before = model.snapshot()
                op = model.next_sort_operation()
                after = model.snapshot()
                if op is None:
                    break
                steps.append((before, after, op))
            if steps:
                view.animate_full_sorting(steps)
                return True, f"完成 {len(steps)} 次冒泡交换。"
            return False, "排序阶段已完成，等待合并。"

        if stage in (HuffmanModel.STAGE_BUILDING, HuffmanModel.STAGE_COMPLETE):
            if model.is_complete():
                return False, "哈夫曼树已完成。"
            before = model.snapshot()
            info = model.perform_merge()
            after = model.snapshot()
            if info:
                view.animate_merge_step(before, after, info)
                return True, f"合并节点 {info['left_id']} 与 {info['right_id']}。"
            return False, "当前无可合并的节点。"

        raise CommandExecutionError("请先执行 INIT 指令。")

    # ---------- 解析辅助 ----------

    def _parse_list_argument(
        self,
        arg_str: str,
        allow_empty: bool = True,
        require_numeric: bool = False,
    ) -> List[Any]:
        if not arg_str.strip():
            if allow_empty:
                return []
            raise CommandSyntaxError("该动作需要提供列表参数。")

        text = arg_str.strip()
        values: Optional[List[Any]] = None

        if text.startswith("["):
            try:
                parsed = json.loads(text)
                if isinstance(parsed, list):
                    values = parsed
            except json.JSONDecodeError:
                values = None

        if values is None:
            tokens = [tok.strip() for tok in text.split(",") if tok.strip()]
            values = [self._coerce_value(tok) for tok in tokens]

        if not values and not allow_empty:
            raise CommandSyntaxError("列表参数不能为空。")

        if require_numeric:
            values = [self._coerce_numeric(v) for v in values]

        return values

    def _parse_index_and_value(self, arg_str: str) -> Tuple[int, Any]:
        if not arg_str.strip():
            raise CommandSyntaxError("需要提供索引与值。")
        parts = arg_str.strip().split(None, 1)
        if len(parts) < 2:
            raise CommandSyntaxError("缺少值参数。")
        index = self._parse_index_only(parts[0])
        value = self._coerce_value(parts[1].strip())
        return index, value

    @staticmethod
    def _parse_index_only(token: str) -> int:
        token = token.strip()
        if not token:
            raise CommandSyntaxError("索引不能为空。")
        try:
            index = int(token, 10)
        except ValueError as exc:
            raise CommandSyntaxError(f"索引必须是整数：{token}") from exc
        if index < 0:
            raise CommandSyntaxError("索引必须是非负整数。")
        return index

    @staticmethod
    def _coerce_value(token: Any) -> Any:
        if token is None:
            return None
        if isinstance(token, (int, float)):
            return token
        text = str(token).strip()
        if not text:
            return "∅"
        if (text.startswith('"') and text.endswith('"')) or (text.startswith("'") and text.endswith("'")):
            return text[1:-1]
        if text.lower() in {"null", "none"}:
            return None
        try:
            return int(text, 10)
        except ValueError:
            try:
                return float(text)
            except ValueError:
                return text

    @staticmethod
    def _coerce_numeric(value: Any) -> float:
        if isinstance(value, (int, float)):
            return value
        text = str(value).strip()
        if not text:
            raise CommandSyntaxError("需要提供数值。")
        try:
            return int(text, 10)
        except ValueError:
            try:
                return float(text)
            except ValueError as exc:
                raise CommandSyntaxError(f"必须是数值：{value}") from exc

    @staticmethod
    def _parse_optional_int(arg_str: str, default: int, min_value: int = 1) -> int:
        text = (arg_str or "").strip()
        if not text:
            return default
        try:
            value = int(text, 10)
        except ValueError as exc:
            raise CommandSyntaxError(f"必须是整数：{text}") from exc
        if value < min_value:
            raise CommandSyntaxError(f"取值必须 ≥ {min_value}。")
        return value