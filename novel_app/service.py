"""Application service coordinating memory, generation and versions."""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

from .database import NovelDatabase
from .llm import AgentGateway
from .memory import MemoryManager


class NovelService:
    def __init__(
        self,
        database: NovelDatabase,
        gateway: AgentGateway,
        memory: MemoryManager,
    ):
        self.database = database
        self.gateway = gateway
        self.memory = memory

    @staticmethod
    def _load_memory(project: dict[str, Any]) -> dict[str, Any] | None:
        raw = project.get("memory_json")
        if not raw:
            return None
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            return None

    def _plan(
        self, context: str, requirements: str, word_limit: int
    ) -> str:
        prompt = f"""
为下一段小说续写拟定一个简短、可执行的写作计划，包含：
承接点、核心冲突推进、人物行动、伏笔处理和结尾钩子。
不要写正文，不新增与现有设定冲突的内容。

上下文：
{context}

额外要求：{requirements or "无"}
目标字数：约 {word_limit} 字
""".strip()
        return self.gateway.call("writing_bot", prompt)

    @staticmethod
    def _writing_prompt(
        context: str,
        requirements: str,
        word_limit: int,
        plan: str,
    ) -> str:
        plan_section = f"\n\n【本段写作计划】\n{plan}" if plan else ""
        return f"""
请根据以下材料续写小说正文。直接输出正文，不解释，不重复已有段落。
首句必须自然承接最近场景；严格遵守人物、世界规则、叙述视角和语言风格。
推进当前冲突，并为下一段保留自然衔接点。

{context}
{plan_section}

【额外写作要求】
{requirements or "无"}

【长度要求】
约 {word_limit} 个中文字符，优先保证完整场景，不要输出标题或字数说明。
""".strip()

    def generate(
        self,
        project_id: str,
        owner_token: str,
        action: str,
    ) -> Iterator[dict[str, Any]]:
        project = self.database.get_project(project_id, owner_token)
        if not project:
            yield {"type": "error", "content": "项目不存在或无权访问"}
            return

        active = self.database.active_generations(project_id)
        if action == "initial" and active:
            yield {"type": "error", "content": "初次续写已经完成，请使用继续续写"}
            return
        if action == "restart":
            position = active[-1]["position"] if active else 1
            context_segments = [item["content"] for item in active[:-1]]
        else:
            position = (active[-1]["position"] + 1) if active else 1
            context_segments = [item["content"] for item in active]

        try:
            memory = self._load_memory(project)
            if not memory and len(project["original_text"]) > self.memory.threshold:
                yield {"type": "status", "content": "正在分块建立小说长期记忆…"}
                memory = self.memory.build_memory(project["original_text"])
                self.database.set_memory(project_id, owner_token, memory)
                yield {"type": "status", "content": "长期记忆已建立"}

            context = self.memory.context_for(
                project["original_text"],
                context_segments,
                memory,
            )
            plan = ""
            if project["writing_mode"] == "standard":
                yield {"type": "status", "content": "正在规划本段情节…"}
                plan = self._plan(
                    context,
                    project["requirements"],
                    project["word_limit"],
                )

            yield {"type": "status", "content": "正在生成正文…"}
            prompt = self._writing_prompt(
                context,
                project["requirements"],
                project["word_limit"],
                plan,
            )
            chunks: list[str] = []
            for chunk in self.gateway.stream("writing_bot", prompt):
                chunks.append(chunk)
                yield {"type": "content", "content": chunk}
            content = "".join(chunks).strip()
            if not content:
                raise RuntimeError("写作模型返回了空内容")

            consistency_report = ""
            if project["writing_mode"] == "standard":
                yield {"type": "status", "content": "正在进行基础一致性检查…"}
                try:
                    consistency_report = self.memory.consistency_report(memory, content)
                except Exception as exc:
                    consistency_report = f"一致性检查未完成：{exc}"

            saved = self.database.save_generation(
                project_id=project_id,
                position=position,
                content=content,
                plan=plan,
                consistency_report=consistency_report,
            )

            try:
                if memory:
                    updated_memory = self.memory.update_memory(memory, content)
                elif len(project["original_text"]) + sum(
                    len(item) for item in context_segments
                ) + len(content) > self.memory.threshold:
                    updated_memory = self.memory.build_memory(
                        project["original_text"]
                        + "\n\n"
                        + "\n\n".join(context_segments + [content])
                    )
                else:
                    updated_memory = None
                if updated_memory:
                    self.database.set_memory(project_id, owner_token, updated_memory)
            except Exception:
                # A memory refresh failure must not discard a successful chapter.
                pass

            if consistency_report:
                yield {
                    "type": "review",
                    "content": consistency_report,
                }
            yield {
                "type": "complete",
                "content": "续写完成",
                "generation_id": saved["id"],
            }
        except Exception as exc:
            yield {"type": "error", "content": f"生成失败：{exc}"}
