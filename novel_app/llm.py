"""Small adapter around Qwen Agent with test-friendly streaming behavior."""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Iterator
from typing import Any

from .config import validate_llm_config


logger = logging.getLogger(__name__)


def _content_from_response(response: Any) -> str:
    if isinstance(response, dict):
        return str(response.get("content", ""))
    if isinstance(response, list):
        messages = [
            item for item in response
            if isinstance(item, dict) and item.get("content") is not None
        ]
        assistant_messages = [
            item for item in messages if item.get("role") in (None, "assistant")
        ]
        selected = (
            assistant_messages[-1]
            if assistant_messages
            else (messages[-1] if messages else {})
        )
        return str(selected.get("content", ""))
    return ""


class AgentGateway:
    def __init__(
        self,
        llm_config: dict[str, Any],
        prompts: dict[str, str],
        agents: dict[str, Any] | None = None,
    ):
        self.llm_config = llm_config
        self.prompts = prompts
        self._agents = agents or {}

    def _agent(self, name: str) -> Any:
        if name in self._agents:
            return self._agents[name]
        validate_llm_config(self.llm_config)
        try:
            from qwen_agent.agents import Assistant
        except ImportError as exc:
            raise RuntimeError("未安装 qwen-agent，请先执行 pip install -r requirements.txt") from exc
        prompt_key = "summary_instruction" if name == "summary_bot" else "writing_instruction"
        self._agents[name] = Assistant(
            llm=self.llm_config[name],
            system_message=self.prompts[prompt_key],
        )
        return self._agents[name]

    def _log_start(
        self,
        name: str,
        operation: str,
        prompt: str,
        task_id: str | None,
    ) -> tuple[str, float]:
        request_id = uuid.uuid4().hex[:8]
        config = self.llm_config.get(name, {})
        timeout = (config.get("generate_cfg") or {}).get("request_timeout")
        logger.info(
            "LLM request started | task=%s id=%s operation=%s agent=%s "
            "model=%s endpoint=%s prompt_chars=%d timeout=%ss",
            task_id or "-",
            request_id,
            operation,
            name,
            config.get("model") or "unknown",
            config.get("model_server") or "unknown",
            len(prompt),
            timeout if timeout is not None else "default",
        )
        return request_id, time.monotonic()

    def call(
        self,
        name: str,
        text: str,
        operation: str = "call",
        task_id: str | None = None,
    ) -> str:
        request_id, started_at = self._log_start(
            name,
            operation,
            text,
            task_id,
        )
        emitted = ""
        first_content_at: float | None = None
        try:
            for response in self._agent(name).run(
                messages=[{"role": "user", "content": text}]
            ):
                content = _content_from_response(response)
                if not content:
                    continue
                if first_content_at is None:
                    first_content_at = time.monotonic()
                    logger.info(
                        "LLM first content | id=%s operation=%s latency=%.2fs",
                        request_id,
                        operation,
                        first_content_at - started_at,
                    )
                if content.startswith(emitted):
                    emitted = content
                else:
                    emitted += content
            if not emitted.strip():
                raise RuntimeError(f"{name} 返回了空响应")
            logger.info(
                "LLM request completed | id=%s operation=%s duration=%.2fs "
                "response_chars=%d",
                request_id,
                operation,
                time.monotonic() - started_at,
                len(emitted),
            )
            return emitted
        except Exception:
            logger.exception(
                "LLM request failed | id=%s operation=%s duration=%.2fs",
                request_id,
                operation,
                time.monotonic() - started_at,
            )
            raise

    def stream(
        self,
        name: str,
        text: str,
        operation: str = "stream",
        task_id: str | None = None,
    ) -> Iterator[str]:
        request_id, started_at = self._log_start(
            name,
            operation,
            text,
            task_id,
        )
        emitted = ""
        first_content_at: float | None = None
        next_progress_chars = 1000
        try:
            for response in self._agent(name).run(
                messages=[{"role": "user", "content": text}]
            ):
                content = _content_from_response(response)
                if not content:
                    continue
                if content.startswith(emitted):
                    chunk = content[len(emitted):]
                    emitted = content
                else:
                    chunk = content
                    emitted += content
                if not chunk:
                    continue
                if first_content_at is None:
                    first_content_at = time.monotonic()
                    logger.info(
                        "LLM first content | id=%s operation=%s latency=%.2fs",
                        request_id,
                        operation,
                        first_content_at - started_at,
                    )
                if len(emitted) >= next_progress_chars:
                    logger.info(
                        "LLM streaming progress | id=%s operation=%s "
                        "response_chars=%d elapsed=%.2fs",
                        request_id,
                        operation,
                        len(emitted),
                        time.monotonic() - started_at,
                    )
                    next_progress_chars = ((len(emitted) // 1000) + 1) * 1000
                yield chunk
            if not emitted.strip():
                raise RuntimeError(f"{name} 返回了空响应")
            logger.info(
                "LLM stream completed | id=%s operation=%s duration=%.2fs "
                "response_chars=%d",
                request_id,
                operation,
                time.monotonic() - started_at,
                len(emitted),
            )
        except GeneratorExit:
            logger.warning(
                "LLM stream cancelled by client | id=%s operation=%s "
                "elapsed=%.2fs response_chars=%d",
                request_id,
                operation,
                time.monotonic() - started_at,
                len(emitted),
            )
            raise
        except Exception:
            logger.exception(
                "LLM stream failed | id=%s operation=%s duration=%.2fs "
                "response_chars=%d",
                request_id,
                operation,
                time.monotonic() - started_at,
                len(emitted),
            )
            raise
