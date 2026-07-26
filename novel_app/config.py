"""Configuration loading and environment-variable resolution."""

from __future__ import annotations

import json
import os
import secrets
from pathlib import Path
from typing import Any, Mapping

from dotenv import dotenv_values


BASE_DIR = Path(__file__).resolve().parent.parent


def _resolve_path(value: str, base_dir: Path) -> str:
    path = Path(value)
    return str(path if path.is_absolute() else base_dir / path)


def _configured_value(
    env_name: str,
    dotenv_config: Mapping[str, str | None],
    json_value: Any,
) -> str:
    """Resolve a non-empty value as environment > .env > config.json."""
    environment_value = (
        str(os.getenv(env_name, "") or "").strip() if env_name else ""
    )
    dotenv_value = (
        str(dotenv_config.get(env_name, "") or "").strip() if env_name else ""
    )
    return environment_value or dotenv_value or str(json_value or "").strip()


def _resolve_bot(
    bot_config: dict[str, Any],
    dotenv_config: Mapping[str, str | None],
) -> dict[str, Any]:
    """Resolve one bot using environment > .env > config.json."""
    resolved = dict(bot_config)
    model_env = str(resolved.pop("model_env", "") or "").strip()
    server_env = str(resolved.pop("model_server_env", "") or "").strip()
    key_env = str(resolved.pop("api_key_env", "") or "").strip()

    resolved["model"] = _configured_value(
        model_env, dotenv_config, resolved.get("model")
    )
    resolved["model_server"] = _configured_value(
        server_env, dotenv_config, resolved.get("model_server")
    )
    resolved["api_key"] = _configured_value(
        key_env, dotenv_config, resolved.get("api_key")
    )
    return resolved


def _load_or_create_secret(
    data_dir: Path,
    dotenv_config: Mapping[str, str | None],
    json_secret: Any = "",
) -> str:
    configured_secret = _configured_value(
        "NOVEL_SECRET_KEY", dotenv_config, json_secret
    )
    if configured_secret:
        return configured_secret

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
    dotenv_config = dotenv_values(
        path.resolve().parent / ".env",
        interpolate=False,
    )

    if "llm_config" not in config or "app_config" not in config:
        raise ValueError("config.json 必须包含 llm_config 和 app_config")

    config["llm_config"] = {
        name: _resolve_bot(bot, dotenv_config)
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
    app_config["secret_key"] = _load_or_create_secret(
        data_dir,
        dotenv_config,
        app_config.get("secret_key", ""),
    )
    return config


def validate_llm_config(llm_config: dict[str, Any]) -> None:
    """Raise a clear error only when an LLM call is actually required."""
    for name in ("summary_bot", "writing_bot"):
        bot = llm_config.get(name, {})
        missing = [key for key in ("model", "model_server", "api_key") if not bot.get(key)]
        if missing:
            joined = "、".join(missing)
            raise RuntimeError(f"{name} 缺少配置：{joined}。请检查环境变量和 config.json")
