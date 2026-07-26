from __future__ import annotations

import sqlite3
from pathlib import Path

from novel_app.database import NovelDatabase


def test_legacy_projects_are_migrated_to_chapters(tmp_path: Path):
    database_path = tmp_path / "legacy.db"
    connection = sqlite3.connect(database_path)
    connection.executescript(
        """
        CREATE TABLE projects (
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

        CREATE TABLE generations (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            position INTEGER NOT NULL,
            version INTEGER NOT NULL,
            content TEXT NOT NULL,
            plan TEXT NOT NULL DEFAULT '',
            consistency_report TEXT NOT NULL DEFAULT '',
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            UNIQUE(project_id, position, version)
        );

        INSERT INTO projects VALUES (
            'project-1', 'owner-1', '旧项目', '旧原稿', '保持悬疑',
            1000, 'standard', NULL, '2026-01-01', '2026-01-01'
        );
        INSERT INTO generations VALUES (
            'generation-1', 'project-1', 1, 1, '旧续写',
            '旧计划', '无冲突', 1, '2026-01-02'
        );
        """
    )
    connection.commit()
    connection.close()

    database = NovelDatabase(str(database_path))
    chapters = database.list_chapters("project-1")

    assert [chapter["kind"] for chapter in chapters] == ["source", "draft"]
    assert chapters[0]["active_version"]["content"] == "旧原稿"
    assert chapters[1]["active_version"]["content"] == "旧续写"
    assert chapters[1]["active_version"]["id"] == "generation-1"
