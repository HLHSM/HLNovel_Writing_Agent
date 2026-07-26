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
                """
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
        self, project_id: str, owner_token: str, memory: dict[str, Any]
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE projects SET memory_json = ?, updated_at = ?
                WHERE id = ? AND owner_token = ?
                """,
                (
                    json.dumps(memory, ensure_ascii=False),
                    utc_now(),
                    project_id,
                    owner_token,
                ),
            )

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
