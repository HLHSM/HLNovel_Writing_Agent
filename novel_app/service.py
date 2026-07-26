"""Application service coordinating chapters, memory and version history."""

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

    @staticmethod
    def _chapter_content(chapter: dict[str, Any]) -> str:
        version = chapter.get("active_version") or {}
        return str(version.get("content") or "")

    @classmethod
    def _combined_text(cls, chapters: list[dict[str, Any]]) -> str:
        return "\n\n".join(
            cls._chapter_content(chapter)
            for chapter in chapters
            if cls._chapter_content(chapter).strip()
        )

    def _memory_for_text(self, text: str) -> dict[str, Any] | None:
        if len(text) <= self.memory.threshold:
            return None
        return self.memory.build_memory(text)

    def _sync_project_memory(
        self,
        project_id: str,
        owner_token: str,
    ) -> dict[str, Any] | None:
        """Rebuild canonical memory from the currently active chapter chain."""
        text = self._combined_text(self.database.list_chapters(project_id))
        rebuilt = self._memory_for_text(text)
        self.database.set_memory(project_id, owner_token, rebuilt)
        return rebuilt

    def _plan(
        self, context: str, requirements: str, word_limit: int, chapter_title: str
    ) -> str:
        prompt = f"""
为小说章节《{chapter_title}》拟定一个简短、可执行的写作计划，包含：
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
        chapter_title: str,
    ) -> str:
        plan_section = f"\n\n【本章写作计划】\n{plan}" if plan else ""
        return f"""
请根据以下材料撰写小说章节《{chapter_title}》。直接输出正文，不解释，
不重复已有段落。首句必须自然承接最近场景；严格遵守人物、世界规则、
叙述视角和语言风格。推进当前冲突，并为下一章保留自然衔接点。

{context}
{plan_section}

【额外写作要求】
{requirements or "无"}

【长度要求】
约 {word_limit} 个中文字符，优先保证完整场景，不要输出标题或字数说明。
""".strip()

    def _context_for_chapters(
        self,
        chapters: list[dict[str, Any]],
        memory_before: dict[str, Any] | None,
    ) -> str:
        source = "\n\n".join(
            self._chapter_content(chapter)
            for chapter in chapters
            if chapter["kind"] == "source"
        )
        generated = [
            self._chapter_content(chapter)
            for chapter in chapters
            if chapter["kind"] != "source"
        ]
        return self.memory.context_for(source, generated, memory_before)

    def _memory_after(
        self,
        memory_before: dict[str, Any] | None,
        prefix_text: str,
        content: str,
    ) -> dict[str, Any] | None:
        if memory_before:
            return self.memory.update_memory(memory_before, content)
        combined = "\n\n".join(part for part in (prefix_text, content) if part)
        return self._memory_for_text(combined)

    def generate(
        self,
        project_id: str,
        owner_token: str,
        action: str,
        chapter_id: str | None = None,
    ) -> Iterator[dict[str, Any]]:
        project = self.database.get_project(project_id, owner_token)
        if not project:
            yield {"type": "error", "content": "项目不存在或无权访问"}
            return

        chapters = self.database.list_chapters(project_id)
        draft_chapters = [chapter for chapter in chapters if chapter["kind"] != "source"]
        if action == "initial" and draft_chapters:
            yield {"type": "error", "content": "初次续写已经完成，请使用继续续写"}
            return

        target: dict[str, Any] | None = None
        if chapter_id:
            target = self.database.get_chapter(project_id, chapter_id)
            if not target:
                yield {"type": "error", "content": "章节不存在"}
                return
        elif action == "restart" and draft_chapters:
            target = draft_chapters[-1]

        prefix_chapters = (
            [chapter for chapter in chapters if chapter["position"] < target["position"]]
            if target
            else chapters
        )
        prefix_text = self._combined_text(prefix_chapters)
        chapter_title = (
            target["title"]
            if target
            else f"第 {len(chapters) + 1} 章(续写)"
        )

        try:
            memory_before = None
            current_memory = self._load_memory(project)
            is_appending = target is None
            if is_appending and current_memory:
                memory_before = current_memory
            elif len(prefix_text) > self.memory.threshold:
                yield {
                    "type": "status",
                    "content": "正在分块建立小说长期记忆并同步当前版本…",
                }
                memory_before = self.memory.build_memory(prefix_text)

            context = self._context_for_chapters(prefix_chapters, memory_before)
            if target:
                context += (
                    "\n\n【待重写章节原文】\n"
                    + self._chapter_content(target)
                )
            plan = ""
            if project["writing_mode"] == "standard":
                yield {"type": "status", "content": "正在规划本段情节（章节级）…"}
                plan = self._plan(
                    context,
                    project["requirements"],
                    project["word_limit"],
                    chapter_title,
                )

            yield {"type": "status", "content": f"正在生成《{chapter_title}》…"}
            prompt = self._writing_prompt(
                context,
                project["requirements"],
                project["word_limit"],
                plan,
                chapter_title,
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
                yield {"type": "status", "content": "正在进行章节一致性检查…"}
                try:
                    consistency_report = self.memory.consistency_report(
                        memory_before, content
                    )
                except Exception as exc:
                    consistency_report = f"一致性检查未完成：{exc}"

            try:
                memory_after = self._memory_after(
                    memory_before, prefix_text, content
                )
            except Exception:
                memory_after = None

            if target:
                saved = self.database.save_chapter_version(
                    project_id,
                    target["id"],
                    content,
                    source_type="ai",
                    plan=plan,
                    consistency_report=consistency_report,
                    requirements=project["requirements"],
                    writing_mode=project["writing_mode"],
                    memory_before=memory_before,
                    memory_after=memory_after,
                )
                saved_chapter_id = target["id"]
            else:
                created = self.database.create_chapter(
                    project_id,
                    chapter_title,
                    content,
                    source_type="ai",
                    plan=plan,
                    consistency_report=consistency_report,
                    requirements=project["requirements"],
                    writing_mode=project["writing_mode"],
                    memory_before=memory_before,
                    memory_after=memory_after,
                )
                saved = created["active_version"]
                saved_chapter_id = created["id"]

            has_later_chapters = bool(
                target
                and any(
                    chapter["position"] > target["position"] for chapter in chapters
                )
            )
            if has_later_chapters:
                try:
                    self._sync_project_memory(project_id, owner_token)
                except Exception:
                    self.database.set_memory(project_id, owner_token, None)
            else:
                self.database.set_memory(
                    project_id, owner_token, memory_after
                )

            if consistency_report:
                yield {"type": "review", "content": consistency_report}
            yield {
                "type": "complete",
                "content": "章节生成完成",
                "generation_id": saved["id"],
                "chapter_id": saved_chapter_id,
            }
        except Exception as exc:
            yield {"type": "error", "content": f"生成失败：{exc}"}

    def create_manual_chapter(
        self,
        project_id: str,
        owner_token: str,
        title: str,
        content: str = "",
    ) -> dict[str, Any]:
        if not self.database.get_project(project_id, owner_token):
            raise ValueError("项目不存在")
        chapter = self.database.create_chapter(
            project_id,
            title or "未命名章节",
            content,
            source_type="manual",
        )
        if content:
            try:
                self._sync_project_memory(project_id, owner_token)
            except Exception:
                self.database.set_memory(project_id, owner_token, None)
        return chapter

    def save_manual_chapter(
        self,
        project_id: str,
        owner_token: str,
        chapter_id: str,
        title: str,
        content: str,
    ) -> dict[str, Any]:
        project = self.database.get_project(project_id, owner_token)
        chapter = self.database.get_chapter(project_id, chapter_id)
        if not project or not chapter:
            raise ValueError("章节不存在")
        chapters = self.database.list_chapters(project_id)
        prefix = [
            item for item in chapters if item["position"] < chapter["position"]
        ]
        prefix_text = self._combined_text(prefix)
        memory_before = self._memory_for_text(prefix_text)
        memory_after = self._memory_after(memory_before, prefix_text, content)
        saved = self.database.save_chapter_version(
            project_id,
            chapter_id,
            content,
            title=title or chapter["title"],
            source_type="manual",
            requirements=project["requirements"],
            writing_mode=project["writing_mode"],
            memory_before=memory_before,
            memory_after=memory_after,
        )
        has_later_chapters = any(
            item["position"] > chapter["position"] for item in chapters
        )
        try:
            if has_later_chapters:
                self._sync_project_memory(project_id, owner_token)
            else:
                self.database.set_memory(project_id, owner_token, memory_after)
        except Exception:
            self.database.set_memory(project_id, owner_token, None)
        return saved

    def restore_version(
        self,
        project_id: str,
        owner_token: str,
        version_id: str,
    ) -> dict[str, Any] | None:
        if not self.database.get_project(project_id, owner_token):
            return None
        restored = self.database.restore_chapter_version(project_id, version_id)
        if not restored:
            return None
        try:
            self._sync_project_memory(project_id, owner_token)
        except Exception:
            self.database.set_memory(project_id, owner_token, None)
        return restored

    def delete_chapter(
        self,
        project_id: str,
        owner_token: str,
        chapter_id: str,
    ) -> bool:
        if not self.database.get_project(project_id, owner_token):
            return False
        deleted = self.database.delete_chapter(project_id, chapter_id)
        if deleted:
            try:
                self._sync_project_memory(project_id, owner_token)
            except Exception:
                self.database.set_memory(project_id, owner_token, None)
        return deleted
