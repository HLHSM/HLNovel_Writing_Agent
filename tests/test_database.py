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


def test_unedited_single_source_project_is_split_on_upgrade(tmp_path: Path):
    database_path = tmp_path / "chapterized.db"
    database = NovelDatabase(str(database_path))
    project = database.create_project(
        owner_token="owner-1",
        title="旧项目",
        original_text="尚未分章的旧原稿",
        requirements="",
        word_limit=1000,
        writing_mode="standard",
    )
    database.create_chapter(project["id"], "旧续写(续写)", "续写内容")
    source = database.list_chapters(project["id"])[0]
    headed_text = "第一章 相遇\n第一章正文。\n\n第二章 雨夜\n第二章正文。"
    with database.connect() as connection:
        connection.execute(
            "UPDATE chapter_versions SET content = ? WHERE chapter_id = ?",
            (headed_text, source["id"]),
        )
        connection.execute(
            "UPDATE projects SET original_text = ? WHERE id = ?",
            (headed_text, project["id"]),
        )

    upgraded = NovelDatabase(str(database_path))
    chapters = upgraded.list_chapters(project["id"])

    assert [chapter["title"] for chapter in chapters] == [
        "第一章 相遇",
        "第二章 雨夜",
        "旧续写(续写)",
    ]
    assert [chapter["position"] for chapter in chapters] == [1, 2, 3]
    assert chapters[0]["active_version"]["content"] == "第一章正文。"
    assert chapters[1]["active_version"]["content"] == "第二章正文。"


def test_edited_source_project_is_not_resplit_on_upgrade(tmp_path: Path):
    database_path = tmp_path / "edited.db"
    database = NovelDatabase(str(database_path))
    project = database.create_project(
        owner_token="owner-1",
        title="已编辑项目",
        original_text="未分章原稿",
        requirements="",
        word_limit=1000,
        writing_mode="standard",
    )
    source = database.list_chapters(project["id"])[0]
    database.save_chapter_version(
        project["id"],
        source["id"],
        "第一章 相遇\n人工编辑过的内容。\n\n第二章 雨夜\n不能自动覆盖。",
    )

    upgraded = NovelDatabase(str(database_path))
    chapters = upgraded.list_chapters(project["id"])

    assert len(chapters) == 1
    assert len(chapters[0]["versions"]) == 2
