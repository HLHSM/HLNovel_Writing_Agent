from __future__ import annotations

import io

from .conftest import consume_stream, create_project


def test_initial_word_limit_is_persisted_and_used(client, app):
    project_id = create_project(client, word_limit=2345)
    stream = consume_stream(client, f"/stream/{project_id}")

    assert '"type": "complete"' in stream
    project = client.get(f"/api/projects/{project_id}").get_json()["project"]
    assert project["word_limit"] == 2345
    assert project["active_generations"][0]["content"] == "林舟握紧钥匙，推开了门。"
    draft_prompt = app.extensions["fake_writing"].calls[-1]
    assert "2345" in draft_prompt


def test_project_is_isolated_by_browser_session(app):
    owner = app.test_client()
    stranger = app.test_client()
    project_id = create_project(owner)

    assert owner.get(f"/api/projects/{project_id}").status_code == 200
    assert stranger.get(f"/api/projects/{project_id}").status_code == 404
    assert stranger.delete(f"/api/projects/{project_id}").status_code == 404


def test_long_text_is_chunked_and_memory_is_cached(client, app):
    project_id = create_project(client, text="林舟沿着走廊前进。" * 30)
    stream = consume_stream(client, f"/stream/{project_id}")

    assert "正在分块建立小说长期记忆" in stream
    summary = app.extensions["fake_summary"]
    chunk_calls = [call for call in summary.calls if "个分块" in call]
    assert len(chunk_calls) > 1
    project = client.get(f"/api/projects/{project_id}").get_json()["project"]
    assert project["has_memory"] is True


def test_failed_restart_keeps_active_version(client, app):
    project_id = create_project(client)
    consume_stream(client, f"/stream/{project_id}")
    before = client.get(f"/api/projects/{project_id}").get_json()["project"]
    active_id = before["active_generations"][0]["id"]

    app.extensions["fake_writing"].fail_next_draft = True
    stream = consume_stream(client, f"/restart/{project_id}")

    assert '"type": "error"' in stream
    after = client.get(f"/api/projects/{project_id}").get_json()["project"]
    assert after["active_generations"][0]["id"] == active_id
    assert len(after["generation_history"]) == 1


def test_restart_creates_restorable_version(client, app):
    writing = app.extensions["fake_writing"]
    writing.writing_outputs = ["第一版正文", "第二版正文"]
    project_id = create_project(client)
    consume_stream(client, f"/stream/{project_id}")
    consume_stream(client, f"/restart/{project_id}")

    project = client.get(f"/api/projects/{project_id}").get_json()["project"]
    history = project["generation_history"]
    assert len(history) == 2
    assert project["active_generations"][0]["content"] == "第二版正文"

    first = next(item for item in history if item["version"] == 1)
    response = client.post(
        f"/api/projects/{project_id}/restore/{first['id']}"
    )
    assert response.status_code == 200
    restored = client.get(f"/api/projects/{project_id}").get_json()["project"]
    assert restored["active_generations"][0]["content"] == "第一版正文"


def test_upload_extension_and_word_limit_are_validated(client):
    invalid_file = client.post(
        "/process",
        data={
            "file": (io.BytesIO(b"not a novel"), "novel.exe"),
            "word_limit": "1000",
            "writing_mode": "quick",
        },
        content_type="multipart/form-data",
    )
    assert invalid_file.status_code == 400
    assert "仅支持" in invalid_file.get_json()["error"]

    invalid_limit = client.post(
        "/process",
        data={
            "text_input": "测试",
            "word_limit": "99999",
            "writing_mode": "quick",
        },
    )
    assert invalid_limit.status_code == 400
    assert "100–10000" in invalid_limit.get_json()["error"]


def test_standard_mode_plans_and_checks_consistency(client, app):
    project_id = create_project(client, writing_mode="standard")
    stream = consume_stream(client, f"/stream/{project_id}")

    assert "正在规划本段情节" in stream
    assert '"type": "review"' in stream
    project = client.get(f"/api/projects/{project_id}").get_json()["project"]
    generation = project["active_generations"][0]
    assert generation["plan"]
    assert generation["consistency_report"] == "未发现明显一致性问题"
