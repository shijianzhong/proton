"""
Main Copilot service for natural language workflow generation.

Provides multi-turn conversation capability for designing and
generating workflows through natural language interaction.
"""

import json
import logging
import os
from datetime import datetime
from typing import Any, AsyncIterator, Dict, List, Optional
from uuid import uuid4

from ..core.models import (
    CopilotMessage,
    CopilotSession,
    CopilotEvent,
    CopilotEventType,
)
from ..orchestration.workflow import WorkflowManager, get_workflow_manager
from .session_manager import SessionManager
from .tools import CopilotTools, COPILOT_TOOL_DEFINITIONS
from .prompts import COPILOT_SYSTEM_PROMPT

logger = logging.getLogger(__name__)


# Provider default configurations (same as builtin adapter)
PROVIDER_DEFAULTS = {
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "env_key": "OPENAI_API_KEY",
        "default_model": "gpt-4",
        "models": ["gpt-4", "gpt-4-turbo", "gpt-4o", "gpt-4o-mini", "gpt-3.5-turbo"],
    },
    "azure": {
        "base_url": None,  # Requires custom endpoint
        "env_key": "AZURE_OPENAI_API_KEY",
        "default_model": "gpt-4",
        "models": ["gpt-4", "gpt-4-turbo", "gpt-35-turbo"],
    },
    "anthropic": {
        "base_url": "https://api.anthropic.com",
        "env_key": "ANTHROPIC_API_KEY",
        "default_model": "claude-3-opus-20240229",
        "models": ["claude-3-opus-20240229", "claude-3-sonnet-20240229", "claude-3-haiku-20240307"],
    },
    "zhipu": {
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "env_key": "ZHIPU_API_KEY",
        "default_model": "glm-4",
        "models": ["glm-4", "glm-4-plus", "glm-4-air", "glm-4-airx", "glm-4-flash", "glm-4v"],
    },
    "deepseek": {
        "base_url": "https://api.deepseek.com",
        "env_key": "DEEPSEEK_API_KEY",
        "default_model": "deepseek-chat",
        "models": ["deepseek-chat", "deepseek-coder"],
    },
    "qwen": {
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "env_key": "DASHSCOPE_API_KEY",
        "default_model": "qwen-plus",
        "models": ["qwen-turbo", "qwen-plus", "qwen-max", "qwen-max-longcontext"],
    },
    "ollama": {
        "base_url": "http://localhost:11434/v1",
        "env_key": None,
        "default_model": "llama2",
        "models": ["llama2", "llama3", "mistral", "codellama", "qwen"],
    },
    "moonshot": {
        "base_url": "https://api.moonshot.cn/v1",
        "env_key": "MOONSHOT_API_KEY",
        "default_model": "moonshot-v1-8k",
        "models": ["moonshot-v1-8k", "moonshot-v1-32k", "moonshot-v1-128k"],
    },
    "yi": {
        "base_url": "https://api.lingyiwanwu.com/v1",
        "env_key": "YI_API_KEY",
        "default_model": "yi-large",
        "models": ["yi-large", "yi-medium", "yi-spark"],
    },
    "baichuan": {
        "base_url": "https://api.baichuan-ai.com/v1",
        "env_key": "BAICHUAN_API_KEY",
        "default_model": "Baichuan2-Turbo",
        "models": ["Baichuan2-Turbo", "Baichuan2-Turbo-192k"],
    },
}


def _load_copilot_config() -> Dict[str, Any]:
    """Load copilot configuration from config file and environment variables."""
    config = {
        "provider": "openai",
        "model": "gpt-4",
        "api_key": None,
        "base_url": None,
        "temperature": 0.7,
        "max_tokens": 4096,
    }

    # Try to load from config file
    try:
        import yaml
        config_path = os.path.join(
            os.path.dirname(__file__), "..", "..", "config", "default.yaml"
        )
        if os.path.exists(config_path):
            with open(config_path, "r") as f:
                yaml_config = yaml.safe_load(f)
                if yaml_config and "copilot" in yaml_config:
                    copilot_config = yaml_config["copilot"]
                    config["provider"] = copilot_config.get("provider", config["provider"])
                    config["model"] = copilot_config.get("model", config["model"])
                    if copilot_config.get("api_key"):
                        config["api_key"] = copilot_config["api_key"]
                    if copilot_config.get("base_url"):
                        config["base_url"] = copilot_config["base_url"]
                    config["temperature"] = copilot_config.get("temperature", config["temperature"])
                    config["max_tokens"] = copilot_config.get("max_tokens", config["max_tokens"])
    except Exception as e:
        logger.warning(f"Failed to load copilot config from file: {e}")

    # Get provider config
    provider = config["provider"]
    provider_config = PROVIDER_DEFAULTS.get(provider, PROVIDER_DEFAULTS["openai"])

    # Set default base_url from provider if not set
    if not config["base_url"] and provider_config["base_url"]:
        config["base_url"] = provider_config["base_url"]

    # Set default model from provider if using default
    if config["model"] == "gpt-4" and provider != "openai":
        config["model"] = provider_config["default_model"]

    # Environment variables override config file
    # Priority: COPILOT_API_KEY > Provider-specific env key > OPENAI_API_KEY
    env_api_key = os.environ.get("COPILOT_API_KEY")
    if not env_api_key and provider_config["env_key"]:
        env_api_key = os.environ.get(provider_config["env_key"])
    if not env_api_key:
        env_api_key = os.environ.get("OPENAI_API_KEY")
    if env_api_key:
        config["api_key"] = env_api_key

    env_base_url = os.environ.get("COPILOT_BASE_URL") or os.environ.get("OPENAI_BASE_URL")
    if env_base_url:
        config["base_url"] = env_base_url

    env_model = os.environ.get("COPILOT_MODEL")
    if env_model:
        config["model"] = env_model

    return config


class CopilotService:
    """
    Service for natural language workflow generation.

    Manages multi-turn conversations with an LLM to design,
    generate, and modify workflows based on user requirements.

    Configuration priority:
    1. Constructor parameters
    2. Environment variables (COPILOT_API_KEY, COPILOT_BASE_URL, COPILOT_MODEL)
    3. Config file (config/default.yaml)

    Supported providers: openai, azure, anthropic, zhipu, deepseek, qwen, ollama, moonshot, yi, baichuan
    """

    def __init__(
        self,
        workflow_manager: WorkflowManager,
        session_manager: Optional[SessionManager] = None,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
    ):
        # Load config from file and environment
        config = _load_copilot_config()

        self.workflow_manager = workflow_manager
        self.session_manager = session_manager or SessionManager()
        self.tools = CopilotTools(workflow_manager)

        # Use provided values or fall back to config
        self.provider = provider or config["provider"]
        self.model = model or config["model"]
        self._api_key = api_key or config["api_key"]
        self._base_url = base_url or config["base_url"]
        self._client = None

        logger.info(
            f"CopilotService initialized with provider={self.provider}, model={self.model}, "
            f"base_url={self._base_url or 'default'}, "
            f"api_key={'configured' if self._api_key else 'NOT SET'}"
        )

    def _get_client(self):
        """Get or create the OpenAI-compatible client."""
        if self._client is None:
            try:
                from openai import AsyncOpenAI
            except ImportError:
                raise RuntimeError(
                    "openai package is required for CopilotService. "
                    "Install it with: pip install openai"
                )

            # Get provider config
            provider_config = PROVIDER_DEFAULTS.get(self.provider, PROVIDER_DEFAULTS["openai"])

            # Validate API key (Ollama doesn't need one)
            if not self._api_key and self.provider != "ollama":
                env_key_name = provider_config.get("env_key", "OPENAI_API_KEY")
                raise RuntimeError(
                    f"Copilot API key not configured for provider '{self.provider}'. Please set one of:\n"
                    f"  1. Environment variable: COPILOT_API_KEY or {env_key_name}\n"
                    f"  2. Config file: config/default.yaml -> copilot.api_key\n"
                    f"  3. API endpoint: POST /api/copilot/config"
                )

            kwargs = {}
            if self._api_key:
                kwargs["api_key"] = self._api_key
            elif self.provider == "ollama":
                # Ollama doesn't need API key
                kwargs["api_key"] = "ollama"

            if self._base_url:
                kwargs["base_url"] = self._base_url

            self._client = AsyncOpenAI(**kwargs)

        return self._client

    async def update_config(
        self,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
    ) -> None:
        """
        Update copilot configuration at runtime and save to database.

        Args:
            provider: New provider to use (openai, zhipu, deepseek, etc.)
            model: New model to use
            api_key: New API key
            base_url: New base URL for the API (None to use provider default)
        """
        if provider:
            self.provider = provider
            # Update base_url to provider default if not explicitly provided
            provider_config = PROVIDER_DEFAULTS.get(provider, PROVIDER_DEFAULTS["openai"])
            if base_url is None and provider_config["base_url"]:
                self._base_url = provider_config["base_url"]
            # Update model to provider default if not explicitly provided
            if model is None:
                self.model = provider_config["default_model"]

        if model:
            self.model = model
        if api_key:
            self._api_key = api_key
        if base_url is not None:  # Allow empty string to reset
            self._base_url = base_url if base_url else None

        # Reset client so it will be recreated with new config
        self._client = None

        logger.info(
            f"CopilotService config updated: provider={self.provider}, model={self.model}, "
            f"base_url={self._base_url or 'default'}"
        )

        # Save to database after update
        await self.save_to_storage()

    async def save_to_storage(self) -> None:
        """Save current configuration to database."""
        try:
            from ..storage.persistence import get_storage_manager

            storage = get_storage_manager()
            await storage.initialize()

            config_data = {
                "provider": self.provider,
                "model": self.model,
                "api_key": self._api_key,
                "base_url": self._base_url,
            }

            await storage.save_config("copilot", config_data)
            logger.info("Copilot config saved to database")
        except Exception as e:
            logger.error(f"Failed to save copilot config to storage: {e}")

    async def load_from_storage(self) -> None:
        """Load configuration from database."""
        try:
            from ..storage.persistence import get_storage_manager

            storage = get_storage_manager()
            await storage.initialize()

            saved_config = await storage.load_config("copilot")

            if saved_config:
                logger.info("Loading copilot config from database")
                self.provider = saved_config.get("provider", self.provider)
                self.model = saved_config.get("model", self.model)
                self._api_key = saved_config.get("api_key", self._api_key)
                self._base_url = saved_config.get("base_url", self._base_url)
                # Reset client to use new config
                self._client = None
            else:
                logger.info("No saved copilot config found")
        except Exception as e:
            logger.warning(f"Failed to load copilot config from storage: {e}")

    def get_config(self) -> Dict[str, Any]:
        """Get current copilot configuration (without exposing full API key)."""
        provider_config = PROVIDER_DEFAULTS.get(self.provider, PROVIDER_DEFAULTS["openai"])
        return {
            "provider": self.provider,
            "model": self.model,
            "base_url": self._base_url,
            "api_key_configured": bool(self._api_key),
            "api_key_preview": f"{self._api_key[:8]}..." if self._api_key and len(self._api_key) > 8 else None,
            "available_models": provider_config.get("models", []),
            "providers": list(PROVIDER_DEFAULTS.keys()),
        }

    async def create_session(
        self,
        metadata: Optional[Dict] = None
    ) -> CopilotSession:
        """
        Create a new copilot session.

        Args:
            metadata: Optional session metadata

        Returns:
            New CopilotSession
        """
        return await self.session_manager.create_session(metadata)

    async def get_session(self, session_id: str) -> Optional[CopilotSession]:
        """
        Get a copilot session.

        Args:
            session_id: The session ID

        Returns:
            CopilotSession if found
        """
        return await self.session_manager.get_session(session_id)

    async def chat(
        self,
        session_id: str,
        message: str,
        stream: bool = True,
    ) -> AsyncIterator[CopilotEvent]:
        """
        Process a chat message and generate/modify workflow.

        Args:
            session_id: The session ID
            message: User's message
            stream: Whether to stream the response

        Yields:
            CopilotEvent objects as the response progresses
        """
        # Get or create session
        session = await self.session_manager.get_or_create(session_id)

        # Add user message
        session.messages.append(CopilotMessage(
            role="user",
            content=message,
        ))

        # Build messages for LLM
        llm_messages = self._build_llm_messages(session)

        try:
            if stream:
                async for event in self._stream_response(session, llm_messages):
                    yield event
            else:
                async for event in self._get_response(session, llm_messages):
                    yield event
        except Exception as e:
            logger.error(f"Copilot error: {e}")
            yield CopilotEvent(
                type=CopilotEventType.ERROR,
                error=str(e),
            )

        # Save session
        await self.session_manager.save(session)

    async def chat_sync(
        self,
        session_id: str,
        message: str,
    ) -> Dict[str, Any]:
        """
        Process a chat message synchronously (non-streaming).

        Args:
            session_id: The session ID
            message: User's message

        Returns:
            Complete response with content and tool results
        """
        events = []
        content_parts = []
        tool_results = []
        workflow_id = None

        async for event in self.chat(session_id, message, stream=False):
            events.append(event)
            if event.type == CopilotEventType.CONTENT and event.delta:
                content_parts.append(event.delta)
            elif event.type == CopilotEventType.TOOL_RESULT:
                tool_results.append(event.result)
            elif event.type in (CopilotEventType.WORKFLOW_CREATED, CopilotEventType.WORKFLOW_UPDATED):
                workflow_id = event.workflow_id

        return {
            "content": "".join(content_parts),
            "tool_results": tool_results,
            "workflow_id": workflow_id,
        }

    async def _stream_response(
        self,
        session: CopilotSession,
        messages: List[Dict],
    ) -> AsyncIterator[CopilotEvent]:
        """
        Stream LLM response with tool execution.

        Args:
            session: Current session
            messages: LLM messages

        Yields:
            CopilotEvent objects
        """
        client = self._get_client()

        response = await client.chat.completions.create(
            model=self.model,
            messages=messages,
            tools=COPILOT_TOOL_DEFINITIONS,
            tool_choice="auto",
            stream=True,
        )

        collected_content = ""
        tool_calls_data: Dict[int, Dict] = {}

        async for chunk in response:
            if not chunk.choices:
                continue

            delta = chunk.choices[0].delta

            # Handle content
            if delta.content:
                collected_content += delta.content
                yield CopilotEvent(
                    type=CopilotEventType.CONTENT,
                    delta=delta.content,
                )

            # Handle tool calls
            if delta.tool_calls:
                for tc in delta.tool_calls:
                    idx = tc.index
                    if idx not in tool_calls_data:
                        tool_calls_data[idx] = {
                            "id": tc.id or "",
                            "name": "",
                            "arguments": "",
                        }

                    if tc.id:
                        tool_calls_data[idx]["id"] = tc.id
                    if tc.function and tc.function.name:
                        tool_calls_data[idx]["name"] = tc.function.name
                    if tc.function and tc.function.arguments:
                        tool_calls_data[idx]["arguments"] += tc.function.arguments

        # Execute tool calls if any
        tool_messages = []
        if tool_calls_data:
            for idx in sorted(tool_calls_data.keys()):
                tc_data = tool_calls_data[idx]
                tool_name = tc_data["name"]
                tool_id = tc_data["id"]

                try:
                    arguments = json.loads(tc_data["arguments"])
                except json.JSONDecodeError:
                    arguments = {}

                yield CopilotEvent(
                    type=CopilotEventType.TOOL_START,
                    tool_name=tool_name,
                    tool_args=arguments,
                )

                # Execute the tool
                result = await self.tools.execute_tool(tool_name, arguments, session)

                # Determine event type based on tool
                event_type = CopilotEventType.TOOL_RESULT
                workflow_id = None

                if tool_name == "generate_workflow" and result.get("status") == "success":
                    event_type = CopilotEventType.WORKFLOW_CREATED
                    workflow_id = result.get("workflow_id")
                elif tool_name == "patch_workflow" and result.get("status") == "success":
                    event_type = CopilotEventType.WORKFLOW_UPDATED
                    workflow_id = result.get("workflow_id")

                yield CopilotEvent(
                    type=event_type,
                    tool_name=tool_name,
                    result=result,
                    workflow_id=workflow_id,
                )

                tool_messages.append({
                    "role": "tool",
                    "tool_call_id": tool_id,
                    "content": json.dumps(result, ensure_ascii=False),
                })

        # If there were tool calls, get follow-up response
        if tool_calls_data:
            # Build tool call objects for assistant message
            tool_call_objs = []
            for idx in sorted(tool_calls_data.keys()):
                tc_data = tool_calls_data[idx]
                tool_call_objs.append({
                    "id": tc_data["id"],
                    "type": "function",
                    "function": {
                        "name": tc_data["name"],
                        "arguments": tc_data["arguments"],
                    }
                })

            # Add assistant message with tool calls
            messages.append({
                "role": "assistant",
                "content": collected_content or None,
                "tool_calls": tool_call_objs,
            })

            # Add tool results
            messages.extend(tool_messages)

            # Get follow-up response
            followup_response = await client.chat.completions.create(
                model=self.model,
                messages=messages,
                tools=COPILOT_TOOL_DEFINITIONS,
                tool_choice="auto",
                stream=True,
            )

            followup_content = ""
            async for chunk in followup_response:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                if delta.content:
                    followup_content += delta.content
                    yield CopilotEvent(
                        type=CopilotEventType.CONTENT,
                        delta=delta.content,
                    )

            collected_content += followup_content

        # Save assistant message to session
        session.messages.append(CopilotMessage(
            role="assistant",
            content=collected_content,
            tool_calls=[tool_calls_data[idx] for idx in sorted(tool_calls_data.keys())] if tool_calls_data else None,
        ))

        yield CopilotEvent(type=CopilotEventType.COMPLETE)

    async def _get_response(
        self,
        session: CopilotSession,
        messages: List[Dict],
    ) -> AsyncIterator[CopilotEvent]:
        """
        Get non-streaming LLM response with tool execution.

        Args:
            session: Current session
            messages: LLM messages

        Yields:
            CopilotEvent objects
        """
        client = self._get_client()

        response = await client.chat.completions.create(
            model=self.model,
            messages=messages,
            tools=COPILOT_TOOL_DEFINITIONS,
            tool_choice="auto",
        )

        choice = response.choices[0]
        content = choice.message.content or ""

        if content:
            yield CopilotEvent(
                type=CopilotEventType.CONTENT,
                delta=content,
            )

        # Handle tool calls
        if choice.message.tool_calls:
            tool_messages = []

            for tc in choice.message.tool_calls:
                tool_name = tc.function.name
                try:
                    arguments = json.loads(tc.function.arguments)
                except json.JSONDecodeError:
                    arguments = {}

                yield CopilotEvent(
                    type=CopilotEventType.TOOL_START,
                    tool_name=tool_name,
                    tool_args=arguments,
                )

                result = await self.tools.execute_tool(tool_name, arguments, session)

                event_type = CopilotEventType.TOOL_RESULT
                workflow_id = None

                if tool_name == "generate_workflow" and result.get("status") == "success":
                    event_type = CopilotEventType.WORKFLOW_CREATED
                    workflow_id = result.get("workflow_id")
                elif tool_name == "patch_workflow" and result.get("status") == "success":
                    event_type = CopilotEventType.WORKFLOW_UPDATED
                    workflow_id = result.get("workflow_id")

                yield CopilotEvent(
                    type=event_type,
                    tool_name=tool_name,
                    result=result,
                    workflow_id=workflow_id,
                )

                tool_messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": json.dumps(result, ensure_ascii=False),
                })

            # Get follow-up response
            messages.append({
                "role": "assistant",
                "content": content or None,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        }
                    }
                    for tc in choice.message.tool_calls
                ],
            })
            messages.extend(tool_messages)

            followup = await client.chat.completions.create(
                model=self.model,
                messages=messages,
            )

            followup_content = followup.choices[0].message.content or ""
            if followup_content:
                content += followup_content
                yield CopilotEvent(
                    type=CopilotEventType.CONTENT,
                    delta=followup_content,
                )

        # Save assistant message
        session.messages.append(CopilotMessage(
            role="assistant",
            content=content,
        ))

        yield CopilotEvent(type=CopilotEventType.COMPLETE)

    def _build_llm_messages(self, session: CopilotSession) -> List[Dict]:
        """
        Build the message list for the LLM.

        Args:
            session: Current session

        Returns:
            List of message dicts for the LLM API
        """
        messages = [
            {"role": "system", "content": COPILOT_SYSTEM_PROMPT}
        ]

        # Add workflow context if exists
        if session.workflow_id:
            messages[0]["content"] += (
                f"\n\n## Current Workflow\n"
                f"The user is currently working on workflow ID: {session.workflow_id}\n"
                f"Use this ID when calling patch_workflow or get_workflow_summary."
            )

        # Add conversation history
        for msg in session.messages:
            if msg.role == "user":
                messages.append({"role": "user", "content": msg.content})
            elif msg.role == "assistant":
                messages.append({"role": "assistant", "content": msg.content})
            elif msg.role == "tool":
                messages.append({
                    "role": "tool",
                    "content": msg.content,
                    "tool_call_id": msg.tool_results[0]["id"] if msg.tool_results else "",
                })

        return messages


# Global copilot service instance
_global_copilot: Optional[CopilotService] = None


def get_copilot_service() -> CopilotService:
    """Get the global copilot service instance."""
    global _global_copilot
    if _global_copilot is None:
        workflow_manager = get_workflow_manager()
        _global_copilot = CopilotService(workflow_manager=workflow_manager)
    return _global_copilot


def configure_copilot(
    provider: str = "openai",
    model: str = "gpt-4",
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
) -> CopilotService:
    """
    Configure and get the global copilot service.

    Args:
        provider: LLM provider (openai, zhipu, deepseek, qwen, etc.)
        model: LLM model to use
        api_key: API key for the LLM provider
        base_url: Base URL for the LLM API

    Returns:
        Configured CopilotService
    """
    global _global_copilot
    workflow_manager = get_workflow_manager()
    _global_copilot = CopilotService(
        workflow_manager=workflow_manager,
        provider=provider,
        model=model,
        api_key=api_key,
        base_url=base_url,
    )
    return _global_copilot
