"""SQLite persistence for projects, chapters and generation versions."""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class NovelDatabase:
    def __init__(self, path: str):
        self.path = path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS projects (
                    id TEXT PRIMARY KEY,
                    owner_token TEXT NOT NULL,
                    title TEXT NOT NULL,
                    original_text TEXT NOT NULL,
                    requirements TEXT NOT NULL DEFAULT '',
                    word_limit INTEGER NOT NULL DEFAULT 1000,
                    writing_mode TEXT NOT NULL DEFAULT 'standard',
                    memory_json TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_projects_owner_updated
                    ON projects(owner_token, updated_at DESC);

                CREATE TABLE IF NOT EXISTS generations (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    position INTEGER NOT NULL,
                    version INTEGER NOT NULL,
                    content TEXT NOT NULL,
                    plan TEXT NOT NULL DEFAULT '',
                    consistency_report TEXT NOT NULL DEFAULT '',
                    is_active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE,
                    UNIQUE(project_id, position, version)
                );

                CREATE INDEX IF NOT EXISTS idx_generations_project_position
                    ON generations(project_id, position, version);

                CREATE TABLE IF NOT EXISTS chapters (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    position INTEGER NOT NULL,
                    title TEXT NOT NULL,
                    kind TEXT NOT NULL DEFAULT 'draft',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE,
                    UNIQUE(project_id, position)
                );

                CREATE INDEX IF NOT EXISTS idx_chapters_project_position
                    ON chapters(project_id, position);

                CREATE TABLE IF NOT EXISTS chapter_versions (
                    id TEXT PRIMARY KEY,
                    chapter_id TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    content TEXT NOT NULL,
                    plan TEXT NOT NULL DEFAULT '',
                    consistency_report TEXT NOT NULL DEFAULT '',
                    requirements TEXT NOT NULL DEFAULT '',
                    writing_mode TEXT NOT NULL DEFAULT 'standard',
                    source_type TEXT NOT NULL DEFAULT 'ai',
                    memory_before_json TEXT,
                    memory_after_json TEXT,
                    is_active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(chapter_id) REFERENCES chapters(id) ON DELETE CASCADE,
                    UNIQUE(chapter_id, version)
                );

                CREATE INDEX IF NOT EXISTS idx_chapter_versions_active
                    ON chapter_versions(chapter_id, is_active, version);
                """
            )
            self._migrate_legacy_projects(connection)

    @staticmethod
    def _migrate_legacy_projects(connection: sqlite3.Connection) -> None:
        """Turn legacy original text and flat generations into chapter records."""
        projects = connection.execute(
            """
            SELECT p.*
            FROM projects p
            WHERE NOT EXISTS (
                SELECT 1 FROM chapters c WHERE c.project_id = p.id
            )
            """
        ).fetchall()
        for project in projects:
            now = utc_now()
            source_chapter_id = str(uuid.uuid4())
            connection.execute(
                """
                INSERT INTO chapters (
                    id, project_id, position, title, kind, created_at, updated_at
                ) VALUES (?, ?, 1, ?, 'source', ?, ?)
                """,
                (
                    source_chapter_id,
                    project["id"],
                    project["title"] or "导入原稿",
                    now,
                    now,
                ),
            )
            connection.execute(
                """
                INSERT INTO chapter_versions (
                    id, chapter_id, version, content, requirements,
                    writing_mode, source_type, is_active, created_at
                ) VALUES (?, ?, 1, ?, ?, ?, 'import', 1, ?)
                """,
                (
                    str(uuid.uuid4()),
                    source_chapter_id,
                    project["original_text"],
                    project["requirements"],
                    project["writing_mode"],
                    now,
                ),
            )

            positions = connection.execute(
                """
                SELECT DISTINCT position
                FROM generations
                WHERE project_id = ?
                ORDER BY position
                """,
                (project["id"],),
            ).fetchall()
            for chapter_position, generation_position in enumerate(positions, start=2):
                chapter_id = str(uuid.uuid4())
                connection.execute(
                    """
                    INSERT INTO chapters (
                        id, project_id, position, title, kind, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, 'draft', ?, ?)
                    """,
                    (
                        chapter_id,
                        project["id"],
                        chapter_position,
                        f"续写 {generation_position['position']}",
                        now,
                        now,
                    ),
                )
                generations = connection.execute(
                    """
                    SELECT * FROM generations
                    WHERE project_id = ? AND position = ?
                    ORDER BY version
                    """,
                    (project["id"], generation_position["position"]),
                ).fetchall()
                for generation in generations:
                    connection.execute(
                        """
                        INSERT INTO chapter_versions (
                            id, chapter_id, version, content, plan,
                            consistency_report, requirements, writing_mode,
                            source_type, is_active, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'ai', ?, ?)
                        """,
                        (
                            generation["id"],
                            chapter_id,
                            generation["version"],
                            generation["content"],
                            generation["plan"],
                            generation["consistency_report"],
                            project["requirements"],
                            project["writing_mode"],
                            generation["is_active"],
                            generation["created_at"],
                        ),
                    )

    def create_project(
        self,
        owner_token: str,
        title: str,
        original_text: str,
        requirements: str,
        word_limit: int,
        writing_mode: str,
    ) -> dict[str, Any]:
        project_id = str(uuid.uuid4())
        now = utc_now()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO projects (
                    id, owner_token, title, original_text, requirements,
                    word_limit, writing_mode, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    owner_token,
                    title,
                    original_text,
                    requirements,
                    word_limit,
                    writing_mode,
                    now,
                    now,
                ),
            )
            chapter_id = str(uuid.uuid4())
            version_id = str(uuid.uuid4())
            connection.execute(
                """
                INSERT INTO chapters (
                    id, project_id, position, title, kind, created_at, updated_at
                ) VALUES (?, ?, 1, ?, 'source', ?, ?)
                """,
                (chapter_id, project_id, title or "导入原稿", now, now),
            )
            connection.execute(
                """
                INSERT INTO chapter_versions (
                    id, chapter_id, version, content, requirements,
                    writing_mode, source_type, is_active, created_at
                ) VALUES (?, ?, 1, ?, ?, ?, 'import', 1, ?)
                """,
                (
                    version_id,
                    chapter_id,
                    original_text,
                    requirements,
                    writing_mode,
                    now,
                ),
            )
        return self.get_project(project_id, owner_token)

    def list_projects(self, owner_token: str) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT id, title, word_limit, writing_mode, created_at, updated_at
                FROM projects WHERE owner_token = ? ORDER BY updated_at DESC
                """,
                (owner_token,),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_project(self, project_id: str, owner_token: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM projects WHERE id = ? AND owner_token = ?",
                (project_id, owner_token),
            ).fetchone()
        return dict(row) if row else None

    def update_project_settings(
        self,
        project_id: str,
        owner_token: str,
        requirements: str,
        word_limit: int,
        writing_mode: str,
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE projects
                SET requirements = ?, word_limit = ?, writing_mode = ?, updated_at = ?
                WHERE id = ? AND owner_token = ?
                """,
                (requirements, word_limit, writing_mode, utc_now(), project_id, owner_token),
            )

    def set_memory(
        self,
        project_id: str,
        owner_token: str,
        memory: dict[str, Any] | None,
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE projects SET memory_json = ?, updated_at = ?
                WHERE id = ? AND owner_token = ?
                """,
                (
                    json.dumps(memory, ensure_ascii=False) if memory else None,
                    utc_now(),
                    project_id,
                    owner_token,
                ),
            )

    @staticmethod
    def _version_payload(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if not row:
            return None
        payload = dict(row)
        payload["is_active"] = bool(payload["is_active"])
        payload["has_memory_before"] = bool(payload.pop("memory_before_json", None))
        payload["has_memory_after"] = bool(payload.pop("memory_after_json", None))
        return payload

    def list_chapters(self, project_id: str) -> list[dict[str, Any]]:
        with self.connect() as connection:
            chapters = connection.execute(
                """
                SELECT * FROM chapters
                WHERE project_id = ?
                ORDER BY position
                """,
                (project_id,),
            ).fetchall()
            result: list[dict[str, Any]] = []
            for chapter in chapters:
                active = connection.execute(
                    """
                    SELECT * FROM chapter_versions
                    WHERE chapter_id = ? AND is_active = 1
                    ORDER BY version DESC LIMIT 1
                    """,
                    (chapter["id"],),
                ).fetchone()
                versions = connection.execute(
                    """
                    SELECT * FROM chapter_versions
                    WHERE chapter_id = ?
                    ORDER BY version DESC
                    """,
                    (chapter["id"],),
                ).fetchall()
                item = dict(chapter)
                item["active_version"] = self._version_payload(active)
                item["versions"] = [
                    self._version_payload(version) for version in versions
                ]
                result.append(item)
        return result

    def get_chapter(
        self, project_id: str, chapter_id: str
    ) -> dict[str, Any] | None:
        return next(
            (
                chapter
                for chapter in self.list_chapters(project_id)
                if chapter["id"] == chapter_id
            ),
            None,
        )

    def create_chapter(
        self,
        project_id: str,
        title: str,
        content: str = "",
        *,
        source_type: str = "manual",
        plan: str = "",
        consistency_report: str = "",
        requirements: str = "",
        writing_mode: str = "standard",
        memory_before: dict[str, Any] | None = None,
        memory_after: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        chapter_id = str(uuid.uuid4())
        version_id = str(uuid.uuid4())
        now = utc_now()
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT COALESCE(MAX(position), 0) AS max_position
                FROM chapters WHERE project_id = ?
                """,
                (project_id,),
            ).fetchone()
            position = int(row["max_position"]) + 1
            connection.execute(
                """
                INSERT INTO chapters (
                    id, project_id, position, title, kind, created_at, updated_at
                ) VALUES (?, ?, ?, ?, 'draft', ?, ?)
                """,
                (chapter_id, project_id, position, title, now, now),
            )
            connection.execute(
                """
                INSERT INTO chapter_versions (
                    id, chapter_id, version, content, plan,
                    consistency_report, requirements, writing_mode,
                    source_type, memory_before_json, memory_after_json,
                    is_active, created_at
                ) VALUES (?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
                """,
                (
                    version_id,
                    chapter_id,
                    content,
                    plan,
                    consistency_report,
                    requirements,
                    writing_mode,
                    source_type,
                    json.dumps(memory_before, ensure_ascii=False)
                    if memory_before
                    else None,
                    json.dumps(memory_after, ensure_ascii=False)
                    if memory_after
                    else None,
                    now,
                ),
            )
            connection.execute(
                "UPDATE projects SET updated_at = ? WHERE id = ?",
                (now, project_id),
            )
        return self.get_chapter(project_id, chapter_id)

    def save_chapter_version(
        self,
        project_id: str,
        chapter_id: str,
        content: str,
        *,
        title: str | None = None,
        source_type: str = "manual",
        plan: str = "",
        consistency_report: str = "",
        requirements: str = "",
        writing_mode: str = "standard",
        memory_before: dict[str, Any] | None = None,
        memory_after: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        version_id = str(uuid.uuid4())
        now = utc_now()
        with self.connect() as connection:
            chapter = connection.execute(
                """
                SELECT * FROM chapters
                WHERE id = ? AND project_id = ?
                """,
                (chapter_id, project_id),
            ).fetchone()
            if not chapter:
                raise ValueError("章节不存在")
            row = connection.execute(
                """
                SELECT COALESCE(MAX(version), 0) AS max_version
                FROM chapter_versions WHERE chapter_id = ?
                """,
                (chapter_id,),
            ).fetchone()
            version = int(row["max_version"]) + 1
            connection.execute(
                "UPDATE chapter_versions SET is_active = 0 WHERE chapter_id = ?",
                (chapter_id,),
            )
            connection.execute(
                """
                INSERT INTO chapter_versions (
                    id, chapter_id, version, content, plan,
                    consistency_report, requirements, writing_mode,
                    source_type, memory_before_json, memory_after_json,
                    is_active, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
                """,
                (
                    version_id,
                    chapter_id,
                    version,
                    content,
                    plan,
                    consistency_report,
                    requirements,
                    writing_mode,
                    source_type,
                    json.dumps(memory_before, ensure_ascii=False)
                    if memory_before
                    else None,
                    json.dumps(memory_after, ensure_ascii=False)
                    if memory_after
                    else None,
                    now,
                ),
            )
            connection.execute(
                """
                UPDATE chapters
                SET title = COALESCE(?, title), updated_at = ?
                WHERE id = ?
                """,
                (title, now, chapter_id),
            )
            connection.execute(
                "UPDATE projects SET updated_at = ? WHERE id = ?",
                (now, project_id),
            )
        return self.get_chapter(project_id, chapter_id)["active_version"]

    def restore_chapter_version(
        self, project_id: str, version_id: str
    ) -> dict[str, Any] | None:
        with self.connect() as connection:
            target = connection.execute(
                """
                SELECT v.*
                FROM chapter_versions v
                JOIN chapters c ON c.id = v.chapter_id
                WHERE v.id = ? AND c.project_id = ?
                """,
                (version_id, project_id),
            ).fetchone()
            if not target:
                return None
            connection.execute(
                "UPDATE chapter_versions SET is_active = 0 WHERE chapter_id = ?",
                (target["chapter_id"],),
            )
            connection.execute(
                "UPDATE chapter_versions SET is_active = 1 WHERE id = ?",
                (version_id,),
            )
            now = utc_now()
            connection.execute(
                "UPDATE chapters SET updated_at = ? WHERE id = ?",
                (now, target["chapter_id"]),
            )
            connection.execute(
                "UPDATE projects SET updated_at = ? WHERE id = ?",
                (now, project_id),
            )
        payload = self._version_payload(target)
        if payload:
            payload["is_active"] = True
        return payload

    def delete_chapter(self, project_id: str, chapter_id: str) -> bool:
        with self.connect() as connection:
            chapter = connection.execute(
                """
                SELECT kind FROM chapters
                WHERE id = ? AND project_id = ?
                """,
                (chapter_id, project_id),
            ).fetchone()
            if not chapter or chapter["kind"] == "source":
                return False
            cursor = connection.execute(
                "DELETE FROM chapters WHERE id = ? AND project_id = ?",
                (chapter_id, project_id),
            )
            rows = connection.execute(
                """
                SELECT id FROM chapters
                WHERE project_id = ? ORDER BY position
                """,
                (project_id,),
            ).fetchall()
            for position, row in enumerate(rows, start=1):
                connection.execute(
                    "UPDATE chapters SET position = ? WHERE id = ?",
                    (-position, row["id"]),
                )
            for position, row in enumerate(rows, start=1):
                connection.execute(
                    "UPDATE chapters SET position = ? WHERE id = ?",
                    (position, row["id"]),
                )
            connection.execute(
                "UPDATE projects SET updated_at = ? WHERE id = ?",
                (utc_now(), project_id),
            )
        return cursor.rowcount > 0

    def active_generations(self, project_id: str) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM generations
                WHERE project_id = ? AND is_active = 1
                ORDER BY position ASC
                """,
                (project_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def generation_history(self, project_id: str) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM generations
                WHERE project_id = ?
                ORDER BY position ASC, version DESC
                """,
                (project_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def save_generation(
        self,
        project_id: str,
        position: int,
        content: str,
        plan: str = "",
        consistency_report: str = "",
    ) -> dict[str, Any]:
        """Atomically save a version and activate it after generation succeeded."""
        generation_id = str(uuid.uuid4())
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT COALESCE(MAX(version), 0) AS max_version
                FROM generations WHERE project_id = ? AND position = ?
                """,
                (project_id, position),
            ).fetchone()
            version = int(row["max_version"]) + 1
            connection.execute(
                """
                UPDATE generations SET is_active = 0
                WHERE project_id = ? AND position = ?
                """,
                (project_id, position),
            )
            connection.execute(
                """
                INSERT INTO generations (
                    id, project_id, position, version, content, plan,
                    consistency_report, is_active, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?)
                """,
                (
                    generation_id,
                    project_id,
                    position,
                    version,
                    content,
                    plan,
                    consistency_report,
                    utc_now(),
                ),
            )
            connection.execute(
                "UPDATE projects SET updated_at = ? WHERE id = ?",
                (utc_now(), project_id),
            )
            saved = connection.execute(
                "SELECT * FROM generations WHERE id = ?", (generation_id,)
            ).fetchone()
        return dict(saved)

    def restore_generation(
        self, project_id: str, generation_id: str
    ) -> dict[str, Any] | None:
        with self.connect() as connection:
            target = connection.execute(
                """
                SELECT * FROM generations
                WHERE id = ? AND project_id = ?
                """,
                (generation_id, project_id),
            ).fetchone()
            if not target:
                return None
            connection.execute(
                """
                UPDATE generations SET is_active = 0
                WHERE project_id = ? AND position = ?
                """,
                (project_id, target["position"]),
            )
            connection.execute(
                "UPDATE generations SET is_active = 1 WHERE id = ?",
                (generation_id,),
            )
            connection.execute(
                "UPDATE projects SET updated_at = ? WHERE id = ?",
                (utc_now(), project_id),
            )
            restored = connection.execute(
                "SELECT * FROM generations WHERE id = ?", (generation_id,)
            ).fetchone()
        return dict(restored)

    def delete_project(self, project_id: str, owner_token: str) -> bool:
        with self.connect() as connection:
            cursor = connection.execute(
                "DELETE FROM projects WHERE id = ? AND owner_token = ?",
                (project_id, owner_token),
            )
        return cursor.rowcount > 0
