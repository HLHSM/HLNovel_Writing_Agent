"""Hierarchical long-text memory and context-budget management."""

from __future__ import annotations

import json
import re
from typing import Any

from .llm import AgentGateway


MEMORY_KEYS = (
    "overview",
    "characters",
    "world_rules",
    "timeline",
    "open_threads",
    "current_scene",
    "style_profile",
)


def split_text(text: str, chunk_chars: int) -> list[str]:
    """Split at paragraph boundaries where possible."""
    if len(text) <= chunk_chars:
        return [text]
    paragraphs = re.split(r"(\n\s*\n)", text)
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        if len(current) + len(paragraph) <= chunk_chars:
            current += paragraph
            continue
        if current:
            chunks.append(current)
        while len(paragraph) > chunk_chars:
            chunks.append(paragraph[:chunk_chars])
            paragraph = paragraph[chunk_chars:]
        current = paragraph
    if current:
        chunks.append(current)
    return chunks


def parse_memory(raw: str) -> dict[str, Any]:
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        parsed = {"overview": cleaned}
    if not isinstance(parsed, dict):
        parsed = {"overview": str(parsed)}
    for key in MEMORY_KEYS:
        parsed.setdefault(key, [] if key not in ("overview", "current_scene", "style_profile") else "")
    return parsed


class MemoryManager:
    def __init__(self, gateway: AgentGateway, app_config: dict[str, Any]):
        self.gateway = gateway
        self.threshold = int(app_config["text_length_threshold"])
        self.chunk_chars = int(app_config["summary_chunk_chars"])
        self.recent_chars = int(app_config["recent_context_chars"])
        self.context_budget = int(app_config["context_char_budget"])
        self.style_sample_chars = int(app_config["style_sample_chars"])

    @staticmethod
    def _summary_prompt(text: str, label: str) -> str:
        return f"""
请分析以下小说{label}，只输出 JSON，不使用 Markdown。字段必须包括：
overview（本段概述）、characters（人物及当前目标/关系/状态）、
world_rules（世界观规则）、timeline（关键事件顺序）、
open_threads（伏笔和未解决冲突）、current_scene（结尾场景）、
style_profile（视角、语言、节奏、对话和描写特点）。
不得添加原文不存在的设定。

小说内容：
{text}
""".strip()

    def build_memory(self, text: str) -> dict[str, Any]:
        chunks = split_text(text, self.chunk_chars)
        partials = [
            self.gateway.call(
                "summary_bot",
                self._summary_prompt(chunk, f"第 {index + 1}/{len(chunks)} 个分块"),
            )
            for index, chunk in enumerate(chunks)
        ]
        if len(partials) == 1:
            return parse_memory(partials[0])

        merged_input = "\n\n".join(
            f"分块 {index + 1}：\n{partial}"
            for index, partial in enumerate(partials)
        )
        merge_prompt = f"""
将以下分块记忆合并成一份全局小说记忆。只输出 JSON，字段为：
{", ".join(MEMORY_KEYS)}。
合并人物状态和时间线，保留仍未解决的伏笔；后出现的信息优先，
但不得臆造。控制结果长度，使其适合后续小说续写。

{merged_input}
""".strip()
        return parse_memory(self.gateway.call("summary_bot", merge_prompt))

    def update_memory(
        self, memory: dict[str, Any], new_segment: str
    ) -> dict[str, Any]:
        prompt = f"""
根据新生成的小说段落增量更新全局记忆。只输出 JSON，字段为：
{", ".join(MEMORY_KEYS)}。保留仍有效的旧信息，更新人物状态、时间线、
当前场景和伏笔；不要把写作计划或评论写入记忆。

旧记忆：
{json.dumps(memory, ensure_ascii=False)}

新段落：
{new_segment}
""".strip()
        return parse_memory(self.gateway.call("summary_bot", prompt))

    def context_for(
        self,
        original_text: str,
        generated_segments: list[str],
        memory: dict[str, Any] | None,
    ) -> str:
        def clip_both(value: str, limit: int) -> str:
            if len(value) <= limit:
                return value
            half = max(1, limit // 2)
            return value[:half] + "\n…（中间内容已按预算省略）…\n" + value[-half:]

        recent_generated = "\n\n".join(generated_segments)
        memory_text = (
            json.dumps(memory, ensure_ascii=False, separators=(",", ":"))
            if memory
            else ""
        )
        memory_budget = min(
            len(memory_text),
            max(4_000, self.context_budget // 3),
        )
        original_budget = min(
            len(original_text),
            max(self.style_sample_chars, self.context_budget // 3),
        )
        fixed_cost = memory_budget + original_budget + 500
        generated_budget = max(
            self.style_sample_chars,
            self.context_budget - fixed_cost,
        )

        sections: list[str] = []
        if memory:
            sections.append(
                "【全局结构化记忆】\n"
                + clip_both(memory_text, memory_budget)
            )
        original_tail = original_text[-original_budget:]
        sections.append(
            "【原文结尾与风格样例，需直接衔接】\n" + original_tail
        )
        if recent_generated:
            sections.append(
                "【已经接受的近期续写内容】\n"
                + recent_generated[-generated_budget:]
            )
        return "\n\n".join(sections)

    def consistency_report(
        self, memory: dict[str, Any] | None, segment: str
    ) -> str:
        prompt = f"""
检查新续写是否与小说记忆矛盾。重点检查人物身份与状态、时间线、
世界规则、视角、未解决伏笔和重复情节。若无明显问题，只输出
“未发现明显一致性问题”。若有问题，用简短要点列出，不要重写正文。

小说记忆：
{json.dumps(memory or {}, ensure_ascii=False)}

新续写：
{segment}
""".strip()
        return self.gateway.call("summary_bot", prompt)
