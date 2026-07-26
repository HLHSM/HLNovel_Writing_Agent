from __future__ import annotations

import json
from pathlib import Path

from novel_app.config import load_config


def write_config(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "llm_config": {
                    "summary_bot": {
                        "model": "summary-model",
                        "model_server": "https://json.example/v1",
                        "api_key": "json-key",
                        "model_server_env": "TEST_SUMMARY_SERVER",
                        "api_key_env": "TEST_SUMMARY_KEY",
                    },
                    "writing_bot": {
                        "model": "writing-model",
                        "model_server": "https://writing.example/v1",
                        "api_key": "writing-key",
                    },
                },
                "app_config": {
                    "database_path": "data/test.db",
                    "upload_folder": "uploads",
                },
            }
        ),
        encoding="utf-8",
    )


def test_direct_json_model_configuration_is_supported(tmp_path, monkeypatch):
    config_path = tmp_path / "config.json"
    write_config(config_path)
    monkeypatch.delenv("TEST_SUMMARY_SERVER", raising=False)
    monkeypatch.delenv("TEST_SUMMARY_KEY", raising=False)

    config = load_config(config_path)

    summary = config["llm_config"]["summary_bot"]
    assert summary["model_server"] == "https://json.example/v1"
    assert summary["api_key"] == "json-key"


def test_non_empty_environment_values_override_json(tmp_path, monkeypatch):
    config_path = tmp_path / "config.json"
    write_config(config_path)
    monkeypatch.setenv("TEST_SUMMARY_SERVER", "https://env.example/v1")
    monkeypatch.setenv("TEST_SUMMARY_KEY", "env-key")

    config = load_config(config_path)

    summary = config["llm_config"]["summary_bot"]
    assert summary["model_server"] == "https://env.example/v1"
    assert summary["api_key"] == "env-key"


def test_empty_environment_values_fall_back_to_json(tmp_path, monkeypatch):
    config_path = tmp_path / "config.json"
    write_config(config_path)
    monkeypatch.setenv("TEST_SUMMARY_SERVER", "  ")
    monkeypatch.setenv("TEST_SUMMARY_KEY", "")

    config = load_config(config_path)

    summary = config["llm_config"]["summary_bot"]
    assert summary["model_server"] == "https://json.example/v1"
    assert summary["api_key"] == "json-key"
