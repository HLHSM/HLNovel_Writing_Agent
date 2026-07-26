"""Small adapter around Qwen Agent with test-friendly streaming behavior."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from .config import validate_llm_config


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
        selected = assistant_messages[-1] if assistant_messages else (messages[-1] if messages else {})
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

    def call(self, name: str, text: str) -> str:
        emitted = ""
        for response in self._agent(name).run(
            messages=[{"role": "user", "content": text}]
        ):
            content = _content_from_response(response)
            if not content:
                continue
            if content.startswith(emitted):
                emitted = content
            else:
                emitted += content
        if not emitted.strip():
            raise RuntimeError(f"{name} 返回了空响应")
        return emitted

    def stream(self, name: str, text: str) -> Iterator[str]:
        emitted = ""
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
            if chunk:
                yield chunk
