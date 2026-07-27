from __future__ import annotations

import json
from pathlib import Path

import pytest

from novel_app import create_app


MEMORY_RESPONSE = json.dumps(
    {
        "overview": "测试故事",
        "characters": [{"name": "林舟", "goal": "找到钥匙"}],
        "world_rules": ["夜间不能离开灯光"],
        "timeline": ["林舟进入旧宅"],
        "open_threads": ["钥匙的来源"],
        "current_scene": "林舟站在门前",
        "style_profile": "第三人称，简洁悬疑",
    },
    ensure_ascii=False,
)


class SmartFakeAgent:
    def __init__(self, kind: str):
        self.kind = kind
        self.calls: list[str] = []
        self.writing_outputs: list[str] = []
        self.fail_next_draft = False
        self.fail_next_plan = False

    def run(self, messages):
        prompt = messages[-1]["content"]
        self.calls.append(prompt)
        if self.kind == "summary":
            if "检查新续写" in prompt:
                output = "未发现明显一致性问题"
            else:
                output = MEMORY_RESPONSE
        elif "拟定一个简短" in prompt:
            if self.fail_next_plan:
                self.fail_next_plan = False
                raise RuntimeError("模拟规划服务超时")
            output = "承接门前场景，让主角发现新线索。"
        else:
            if self.fail_next_draft:
                self.fail_next_draft = False
                raise RuntimeError("模拟写作服务中断")
            output = (
                self.writing_outputs.pop(0)
                if self.writing_outputs
                else "林舟握紧钥匙，推开了门。"
            )

        midpoint = max(1, len(output) // 2)
        yield [{"role": "assistant", "content": output[:midpoint]}]
        yield [{"role": "assistant", "content": output}]


@pytest.fixture()
def app(tmp_path: Path):
    summary = SmartFakeAgent("summary")
    writing = SmartFakeAgent("writing")
    application = create_app(
        config_overrides={
            "TESTING": True,
            "database_path": str(tmp_path / "novels.db"),
            "upload_folder": str(tmp_path / "uploads"),
            "text_length_threshold": 100,
            "summary_chunk_chars": 40,
            "recent_context_chars": 50,
            "context_char_budget": 300,
            "style_sample_chars": 30,
        },
        agents={"summary_bot": summary, "writing_bot": writing},
    )
    application.extensions["fake_summary"] = summary
    application.extensions["fake_writing"] = writing
    return application


@pytest.fixture()
def client(app):
    return app.test_client()


def create_project(client, text="林舟站在旧宅门前。", **fields):
    payload = {
        "title": fields.get("title", "旧宅"),
        "text_input": text,
        "requirements": fields.get("requirements", "保持悬疑"),
        "word_limit": str(fields.get("word_limit", 1200)),
        "writing_mode": fields.get("writing_mode", "quick"),
    }
    response = client.post("/process", data=payload)
    assert response.status_code == 200
    return response.get_json()["project_id"]


def consume_stream(client, url: str) -> str:
    response = client.get(url, buffered=True)
    assert response.status_code == 200
    return response.get_data(as_text=True)
