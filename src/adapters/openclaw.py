"""
OpenClaw service adapter.

Assumes OpenClaw exposes an OpenAI-compatible chat-completions API.
"""

import json
import logging
import os
from typing import Any, AsyncIterator, Dict, List, Optional
from uuid import uuid4

import aiohttp

from .base import AgentAdapter, AdapterFactory
from ..core.agent_node import AgentNode
from ..core.context import ExecutionContext
from ..core.models import (
    AgentCapabilities,
    AgentResponse,
    AgentResponseUpdate,
    AgentType,
    ChatMessage,
    MessageRole,
    OpenClawConfig,
)

logger = logging.getLogger(__name__)


class OpenClawAgentAdapter(AgentAdapter):
    def __init__(self, node: AgentNode):
        super().__init__(node)
        self._config: Optional[OpenClawConfig] = None
        self._session: Optional[aiohttp.ClientSession] = None

    async def initialize(self) -> None:
        if self._initialized:
            return
        cfg = self.node.config.openclaw_config
        if cfg is None:
            api_base = os.environ.get("OPENCLAW_API_BASE", "").strip()
            if not api_base:
                gateway_url = os.environ.get("OPENCLAW_GATEWAY_URL", "").strip()
                if gateway_url.startswith("ws://"):
                    api_base = "http://" + gateway_url[len("ws://") :]
                elif gateway_url.startswith("wss://"):
                    api_base = "https://" + gateway_url[len("wss://") :]
                elif gateway_url.startswith("http://") or gateway_url.startswith("https://"):
                    api_base = gateway_url
            if not api_base:
                api_base = "http://localhost:18789"
            if api_base.rstrip("/").endswith("/v1"):
                api_base = api_base.rstrip("/")[:-3]
            api_key = (
                os.environ.get("OPENCLAW_API_KEY")
                or os.environ.get("OPENCLAW_GATEWAY_TOKEN")
                or os.environ.get("OPENCLAW_GATEWAY_PASSWORD")
                or None
            )
            cfg = OpenClawConfig(
                api_base=api_base,
                api_key=api_key,
                model=os.environ.get("OPENCLAW_MODEL", "openclaw/default"),
            )
        self._config = cfg
        headers = {"Content-Type": "application/json"}
        if cfg.api_key:
            headers["Authorization"] = f"Bearer {cfg.api_key}"
        self._session = aiohttp.ClientSession(headers=headers)
        self._initialized = True

    async def cleanup(self) -> None:
        if self._session:
            await self._session.close()
            self._session = None

    async def run(
        self,
        messages: List[ChatMessage],
        context: ExecutionContext,
        **kwargs: Any,
    ) -> AgentResponse:
        self._ensure_initialized()
        payload = {
            "model": self._config.model,
            "messages": self._to_openai_messages(messages),
            "stream": False,
            "user": self._config.user_id,
        }
        url = self._build_chat_url(self._config)
        try:
            async with self._session.post(url, json=payload) as resp:
                if resp.status != 200:
                    return self._create_error_response(f"API error: {resp.status}")
                data = await resp.json()
                return self._parse_response(data)
        except aiohttp.ClientError as exc:
            return self._create_error_response(str(exc))

    async def run_stream(
        self,
        messages: List[ChatMessage],
        context: ExecutionContext,
        **kwargs: Any,
    ) -> AsyncIterator[AgentResponseUpdate]:
        self._ensure_initialized()
        payload = {
            "model": self._config.model,
            "messages": self._to_openai_messages(messages),
            "stream": True,
            "user": self._config.user_id,
        }
        url = self._build_chat_url(self._config)
        try:
            async with self._session.post(url, json=payload) as resp:
                if resp.status != 200:
                    yield AgentResponseUpdate(delta_content=f"Error: {resp.status}", is_complete=True)
                    return
                async for line in resp.content:
                    text = line.decode("utf-8").strip()
                    if not text.startswith("data:"):
                        continue
                    data = text[5:].strip()
                    if data == "[DONE]":
                        yield AgentResponseUpdate(delta_content="", is_complete=True)
                        return
                    try:
                        chunk = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    choices = chunk.get("choices") or []
                    if not choices:
                        continue
                    delta = choices[0].get("delta") or {}
                    content = str(delta.get("content") or "")
                    if content:
                        yield AgentResponseUpdate(delta_content=content, is_complete=False)
                    if choices[0].get("finish_reason"):
                        yield AgentResponseUpdate(delta_content="", is_complete=True)
                        return
        except Exception as exc:
            yield AgentResponseUpdate(delta_content=f"Error: {exc}", is_complete=True)

    def get_capabilities(self) -> AgentCapabilities:
        return AgentCapabilities(
            supports_streaming=True,
            supports_tools=True,
            supports_vision=True,
            max_context_length=128000,
            supported_languages=["zh", "en"],
        )

    @staticmethod
    def _build_chat_url(cfg: OpenClawConfig) -> str:
        return f"{cfg.api_base.rstrip('/')}/{cfg.chat_path.lstrip('/')}"

    @staticmethod
    def _to_openai_messages(messages: List[ChatMessage]) -> List[Dict[str, str]]:
        out: List[Dict[str, str]] = []
        for msg in messages:
            role = msg.role.value
            if role == MessageRole.TOOL.value:
                role = MessageRole.ASSISTANT.value
            out.append({"role": role, "content": msg.content})
        return out

    def _parse_response(self, data: Dict[str, Any]) -> AgentResponse:
        choices = data.get("choices") or []
        content = ""
        if choices:
            content = str((choices[0].get("message") or {}).get("content") or "")
        return AgentResponse(
            messages=[
                ChatMessage(
                    role=MessageRole.ASSISTANT,
                    content=content or "[No response from OpenClaw]",
                    name=self.node.name,
                )
            ],
            response_id=str(uuid4()),
            metadata={"model": data.get("model"), "usage": data.get("usage", {})},
            usage=data.get("usage"),
        )

    def _create_error_response(self, error: str) -> AgentResponse:
        return AgentResponse(
            messages=[
                ChatMessage(
                    role=MessageRole.ASSISTANT,
                    content=f"[OpenClaw Error: {error}]",
                    name=self.node.name,
                )
            ],
            response_id=str(uuid4()),
            metadata={"error": error},
        )


AdapterFactory.register(AgentType.OPENCLAW, OpenClawAgentAdapter)
