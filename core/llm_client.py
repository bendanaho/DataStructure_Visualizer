"""core/llm_client.py

通过 OpenAI 兼容接口将自然语言转换为 DSL 指令。
依赖：requests
"""
from __future__ import annotations

import requests
import re
from typing import Optional

from core.command_parser import DSL_SPEC


class LLMClient:
    """封装大模型 HTTP 请求，将自然语言转换为 DSL。"""

    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str = "gpt-4o-mini",
        timeout: int = 30,
    ):
        self.api_key = api_key or ""
        self.base_url = (base_url or "").rstrip("/")
        self.model = model
        self.timeout = timeout

    def translate_to_dsl(self, user_text: str, structure_type: Optional[str] = None) -> str:
        """
        调用大模型，将自然语言描述转换为 DSL。
        返回纯文本指令（不包含 Markdown）。
        """
        if not self.api_key:
            raise ValueError("API Key 未配置。")
        if not self.base_url:
            raise ValueError("Base URL 未配置。")
        if not user_text or not user_text.strip():
            raise ValueError("请输入需要转换的自然语言。")

        endpoint = self.base_url
        if not endpoint.endswith("/chat/completions"):
            endpoint = f"{endpoint}/chat/completions"

        # 修改点：增加了第 5 条规则，明确要求忽略无关内容并输出注释
        system_prompt = (
            "你是一个 DSL 转换器，只负责把用户的中文或英文自然语言"
            "转换成严格的 DSL 指令，每行一条，不添加多余解释。"
            "以下是 DSL 语法规范：\n"
            f"{DSL_SPEC}\n"
            "输出要求：\n"
            "1. 仅输出 DSL 文本，每行一条指令。\n"
            "2. 严禁输出 Markdown 代码块标记（如 ```dsl ... ```），直接输出纯文本。\n"
            "3. 指令需省略结构名称（STRUCTURE），直接以动作（ACTION）开头。\n"
            "4. 若用户需求涉及多个结构，可分行输出，但仍需对每个指令省略结构名前缀。\n"
            "5. 如果用户输入包含与数据结构操作无关（如闲聊、数学计算、通用问答、代码解释等）的内容，"
            "如果全部为无关内容，请直接输出 `# IGNORE: 输入与数据结构操作无关`，严禁回答问题或生成无效指令。"
            "如果只有部分无关内容，请忽略无关内容，输出相关的DSL文本"
        )

        target = structure_type or self._default_structure_hint(user_text)
        user_prompt = (
            f"目标结构：{target or '未指定'}\n"
            f"用户输入：{user_text.strip()}\n"
            "请直接给出可执行的 DSL 指令："
        )

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.1,
            "stream": False,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        try:
            response = requests.post(endpoint, json=payload, headers=headers, timeout=self.timeout)
            response.raise_for_status()
        except requests.exceptions.RequestException as e:
            raise RuntimeError(f"LLM 网络请求失败: {str(e)}")

        data = response.json()
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError(f"LLM 响应格式异常: {data}") from exc

        if not content or not content.strip():
            raise RuntimeError("LLM 没有返回任何 DSL 指令。")

        return self._clean_markdown(content)

    def _clean_markdown(self, text: str) -> str:
        """去除可能存在的 Markdown 代码块标记"""
        text = text.strip()
        # 匹配 ```dsl ... ``` 或 ``` ... ```
        pattern = r"^```(?:\w+)?\s*\n(.*?)\n```$"
        match = re.search(pattern, text, re.DOTALL)
        if match:
            return match.group(1).strip()
        return text

    @staticmethod
    def _default_structure_hint(text: str) -> str:
        lowered = text.lower()
        if "array" in lowered or "数组" in lowered:
            return "Array"
        if "链表" in lowered or "linked" in lowered:
            return "Linked List"
        if "stack" in lowered or "栈" in lowered:
            return "Stack"
        if "树" in lowered or "bst" in lowered:
            return "BST"
        if "avl" in lowered:  # 新增
            return "AVL"
        if "哈夫曼" in lowered or "huffman" in lowered:
            return "Huffman"
        if "双向链表" in text or "双链表" in text or "doubly" in lowered or "double linked" in lowered or "dll" in lowered:
            return "Doubly Linked List"
        return ""