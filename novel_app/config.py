"""Configuration loading and environment-variable resolution."""

from __future__ import annotations

import json
import os
import secrets
from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).resolve().parent.parent


def _resolve_path(value: str, base_dir: Path) -> str:
    path = Path(value)
    return str(path if path.is_absolute() else base_dir / path)


def _resolve_bot(bot_config: dict[str, Any]) -> dict[str, Any]:
    resolved = dict(bot_config)
    server_env = resolved.pop("model_server_env", "")
    key_env = resolved.pop("api_key_env", "")
    if server_env:
        resolved["model_server"] = os.getenv(server_env, resolved.get("model_server", ""))
    if key_env:
        resolved["api_key"] = os.getenv(key_env, resolved.get("api_key", ""))
    return resolved


def _load_or_create_secret(data_dir: Path) -> str:
    env_secret = os.getenv("NOVEL_SECRET_KEY")
    if env_secret:
        return env_secret

    data_dir.mkdir(parents=True, exist_ok=True)
    secret_file = data_dir / ".secret_key"
    if secret_file.exists():
        return secret_file.read_text(encoding="utf-8").strip()

    secret = secrets.token_urlsafe(48)
    secret_file.write_text(secret, encoding="utf-8")
    try:
        secret_file.chmod(0o600)
    except OSError:
        pass
    return secret


def load_config(
    config_path: str | Path | None = None,
    overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Load JSON configuration, resolve secrets and normalize local paths."""
    path = Path(config_path or os.getenv("NOVEL_CONFIG", BASE_DIR / "config.json"))
    with path.open("r", encoding="utf-8") as handle:
        config = json.load(handle)

    if "llm_config" not in config or "app_config" not in config:
        raise ValueError("config.json 必须包含 llm_config 和 app_config")

    config["llm_config"] = {
        name: _resolve_bot(bot)
        for name, bot in config["llm_config"].items()
    }
    app_config = config["app_config"]
    base_dir = path.resolve().parent
    app_config["database_path"] = _resolve_path(
        app_config.get("database_path", "data/novels.db"), base_dir
    )
    app_config["upload_folder"] = _resolve_path(
        app_config.get("upload_folder", "uploads"), base_dir
    )
    app_config.setdefault("allowed_extensions", ["txt", "md"])
    app_config.setdefault("text_length_threshold", 100_000)
    app_config.setdefault("summary_chunk_chars", 24_000)
    app_config.setdefault("recent_context_chars", 12_000)
    app_config.setdefault("context_char_budget", 60_000)
    app_config.setdefault("style_sample_chars", 3_000)
    app_config.setdefault("max_file_size_mb", 50)
    app_config.setdefault("host", "127.0.0.1")
    app_config.setdefault("port", 5000)
    app_config.setdefault("debug", False)

    if overrides:
        app_config.update(overrides)

    data_dir = Path(app_config["database_path"]).parent
    app_config["secret_key"] = _load_or_create_secret(data_dir)
    return config


def validate_llm_config(llm_config: dict[str, Any]) -> None:
    """Raise a clear error only when an LLM call is actually required."""
    for name in ("summary_bot", "writing_bot"):
        bot = llm_config.get(name, {})
        missing = [key for key in ("model", "model_server", "api_key") if not bot.get(key)]
        if missing:
            joined = "、".join(missing)
            raise RuntimeError(f"{name} 缺少配置：{joined}。请检查环境变量和 config.json")
