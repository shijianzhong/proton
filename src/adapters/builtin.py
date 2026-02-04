"""
Built-in agent adapter for agents created through the visual editor.

This adapter handles agents that are fully defined within the platform,
including custom tools, prompt templates, and output formatting.
"""

import logging
import json
import re
import os
import aiohttp
from typing import Any, AsyncIterator, Dict, List, Optional
from uuid import uuid4

from .base import AgentAdapter, AdapterFactory
from ..core.models import (
    AgentType,
    AgentResponse,
    AgentResponseUpdate,
    AgentCapabilities,
    ChatMessage,
    MessageRole,
    BuiltinAgentDefinition,
    BuiltinToolDefinition,
    PromptTemplate,
)
from ..core.context import ExecutionContext
from ..core.agent_node import AgentNode
from ..tools.registry import get_system_tool_registry

logger = logging.getLogger(__name__)


# Provider default configurations
PROVIDER_DEFAULTS = {
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "env_key": "OPENAI_API_KEY",
        "default_model": "gpt-4",
    },
    "azure": {
        "base_url": None,  # Requires custom endpoint
        "env_key": "AZURE_OPENAI_API_KEY",
        "default_model": "gpt-4",
    },
    "anthropic": {
        "base_url": "https://api.anthropic.com",
        "env_key": "ANTHROPIC_API_KEY",
        "default_model": "claude-3-opus-20240229",
    },
    "zhipu": {
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "env_key": "ZHIPU_API_KEY",
        "default_model": "glm-4",
    },
    "deepseek": {
        "base_url": "https://api.deepseek.com",
        "env_key": "DEEPSEEK_API_KEY",
        "default_model": "deepseek-chat",
    },
    "qwen": {
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "env_key": "DASHSCOPE_API_KEY",
        "default_model": "qwen-plus",
    },
    "ollama": {
        "base_url": "http://localhost:11434/v1",
        "env_key": None,
        "default_model": "llama2",
    },
    "moonshot": {
        "base_url": "https://api.moonshot.cn/v1",
        "env_key": "MOONSHOT_API_KEY",
        "default_model": "moonshot-v1-8k",
    },
    "yi": {
        "base_url": "https://api.lingyiwanwu.com/v1",
        "env_key": "YI_API_KEY",
        "default_model": "yi-large",
    },
    "baichuan": {
        "base_url": "https://api.baichuan-ai.com/v1",
        "env_key": "BAICHUAN_API_KEY",
        "default_model": "Baichuan2-Turbo",
    },
}


class BuiltinAgentAdapter(AgentAdapter):
    """
    Adapter for built-in agents created through visual editing.

    Features:
    - Custom tool execution (HTTP, code, transforms)
    - System built-in tools (file, shell, web)
    - Prompt template rendering
    - Output format validation
    - Multi-provider support (OpenAI, Zhipu, DeepSeek, Qwen, etc.)
    """

    def __init__(self, node: AgentNode):
        super().__init__(node)
        self._definition: Optional[BuiltinAgentDefinition] = None
        self._openai_client = None
        self._tools_registry: Dict[str, BuiltinToolDefinition] = {}
        self._system_tool_registry = get_system_tool_registry()
        self._enabled_system_tools: List[str] = []

    async def initialize(self) -> None:
        """Initialize the built-in agent."""
        if self._initialized:
            return

        # Get definition from config
        self._definition = self.node.config.builtin_definition
        if not self._definition:
            # Create default definition from basic config
            self._definition = BuiltinAgentDefinition(
                name=self.node.name,
                description=self.node.description,
                model=self.node.config.model,
                temperature=self.node.config.temperature,
                max_tokens=self.node.config.max_tokens,
            )

        # Build tools registry (custom tools)
        for tool in self._definition.builtin_tools:
            self._tools_registry[tool.name] = tool

        # Set up enabled system tools
        if self._definition.system_tools:
            self._enabled_system_tools = self._definition.system_tools
        else:
            self._enabled_system_tools = []

        # Initialize OpenAI-compatible client
        self._openai_client = self._create_openai_client()

        self._initialized = True
        logger.info(f"Initialized built-in agent: {self._definition.name} (provider: {self._definition.provider}, model: {self._definition.model}, system_tools: {len(self._enabled_system_tools)})")

    def _create_openai_client(self) -> Any:
        """Create OpenAI-compatible client based on provider."""
        try:
            from openai import AsyncOpenAI
        except ImportError:
            logger.error("openai package not installed. Run: pip install openai")
            return None

        provider = self._definition.provider if self._definition else "openai"
        provider_config = PROVIDER_DEFAULTS.get(provider, PROVIDER_DEFAULTS["openai"])

        # Determine base_url
        base_url = self._definition.base_url if self._definition and self._definition.base_url else provider_config["base_url"]

        # Determine api_key
        api_key = None
        if self._definition and self._definition.api_key:
            api_key = self._definition.api_key
        elif provider_config["env_key"]:
            api_key = os.environ.get(provider_config["env_key"])
            # Also try generic OPENAI_API_KEY for compatible providers
            if not api_key and provider != "openai":
                api_key = os.environ.get("OPENAI_API_KEY")

        if not api_key and provider != "ollama":
            logger.warning(f"No API key found for provider {provider}")

        # Create client
        client_kwargs = {}
        if base_url:
            client_kwargs["base_url"] = base_url
        if api_key:
            client_kwargs["api_key"] = api_key
        elif provider == "ollama":
            # Ollama doesn't need API key
            client_kwargs["api_key"] = "ollama"

        logger.info(f"Creating OpenAI client for {provider} with base_url: {base_url}")
        return AsyncOpenAI(**client_kwargs)

    async def run(
        self,
        messages: List[ChatMessage],
        context: ExecutionContext,
        **kwargs: Any,
    ) -> AgentResponse:
        """Execute the built-in agent with multi-turn tool calling support."""
        self._ensure_initialized()

        # Build the complete message list with system prompt
        full_messages = self._build_messages(messages, context, kwargs)

        # Get tools in function calling format
        tools = self._get_tools_for_api()

        if self._openai_client is None:
            return self._create_fallback_response(messages)

        try:
            # Convert to OpenAI format
            openai_messages = self._convert_to_openai_messages(full_messages)

            # Get model and parameters
            model = self._definition.model if self._definition else "gpt-4"
            temperature = self._definition.temperature if self._definition else 0.7
            max_tokens = self._definition.max_tokens if self._definition else 4096

            # Multi-turn tool calling loop
            max_tool_rounds = 5  # Prevent infinite loops
            final_response = None

            for round_num in range(max_tool_rounds):
                # Build request kwargs
                request_kwargs = {
                    "model": model,
                    "messages": openai_messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                }

                # Add tools if available
                if tools:
                    request_kwargs["tools"] = tools
                    request_kwargs["tool_choice"] = "auto"

                # Call the API
                response = await self._openai_client.chat.completions.create(**request_kwargs)

                # Process response
                agent_response = self._convert_from_openai_response(response)

                # If no tool calls, this is the final response
                if not agent_response.tool_calls:
                    final_response = agent_response
                    break

                # Execute tool calls
                agent_response = await self._handle_tool_calls(
                    agent_response, full_messages, context
                )

                # Append assistant message with tool calls to conversation
                assistant_msg = {
                    "role": "assistant",
                    "content": agent_response.messages[0].content if agent_response.messages and agent_response.messages[0].content else None,
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.name,
                                "arguments": json.dumps(tc.arguments, ensure_ascii=False),
                            },
                        }
                        for tc in agent_response.tool_calls
                    ],
                }
                openai_messages.append(assistant_msg)

                # Append tool results to conversation
                for tool_result in agent_response.tool_results:
                    openai_messages.append({
                        "role": "tool",
                        "tool_call_id": tool_result.tool_call_id,
                        "content": tool_result.content,
                    })

                logger.info(f"Tool round {round_num + 1}: executed {len(agent_response.tool_calls)} tool(s), continuing...")

                # Store the response in case we hit max rounds
                final_response = agent_response

            if final_response is None:
                final_response = agent_response

            # Validate and format output
            final_response = self._format_output(final_response)

            return final_response

        except Exception as e:
            logger.error(f"Error running built-in agent: {e}")
            return AgentResponse(
                messages=[ChatMessage(
                    role=MessageRole.ASSISTANT,
                    content=f"Error: {str(e)}",
                    name=self.node.name,
                )],
                response_id=str(uuid4()),
                metadata={"error": str(e)},
            )

    async def run_stream(
        self,
        messages: List[ChatMessage],
        context: ExecutionContext,
        **kwargs: Any,
    ) -> AsyncIterator[AgentResponseUpdate]:
        """Execute with streaming."""
        self._ensure_initialized()

        if self._openai_client is None or not (
            self._definition and self._definition.streaming_enabled
        ):
            # Fall back to non-streaming
            response = await self.run(messages, context, **kwargs)
            for msg in response.messages:
                yield AgentResponseUpdate(
                    delta_content=msg.content,
                    is_complete=True,
                )
            return

        full_messages = self._build_messages(messages, context, kwargs)
        openai_messages = self._convert_to_openai_messages(full_messages)

        try:
            model = self._definition.model if self._definition else "gpt-4"
            temperature = self._definition.temperature if self._definition else 0.7
            max_tokens = self._definition.max_tokens if self._definition else 4096

            stream = await self._openai_client.chat.completions.create(
                model=model,
                messages=openai_messages,
                temperature=temperature,
                max_tokens=max_tokens,
                stream=True,
            )

            async for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    yield AgentResponseUpdate(
                        delta_content=chunk.choices[0].delta.content,
                        is_complete=False,
                    )

            yield AgentResponseUpdate(
                delta_content="",
                is_complete=True,
            )

        except Exception as e:
            yield AgentResponseUpdate(
                delta_content=f"Error: {str(e)}",
                is_complete=True,
            )

    def get_capabilities(self) -> AgentCapabilities:
        """Get agent capabilities."""
        if self._definition:
            return AgentCapabilities(
                supports_streaming=self._definition.streaming_enabled,
                supports_tools=len(self._definition.builtin_tools) > 0,
                supports_vision="vision" in self._definition.model.lower() if self._definition.model else False,
                max_context_length=128000 if "gpt-4" in (self._definition.model or "") else 16000,
            )
        return AgentCapabilities()

    def _build_messages(
        self,
        messages: List[ChatMessage],
        context: ExecutionContext,
        kwargs: Dict[str, Any],
    ) -> List[ChatMessage]:
        """Build complete message list with system prompt."""
        result = []

        # Add system prompt
        if self._definition and self._definition.system_prompt:
            system_content = self._render_template(
                self._definition.system_prompt,
                {**context.shared_state, **kwargs}
            )
            result.append(ChatMessage(
                role=MessageRole.SYSTEM,
                content=system_content,
            ))

        # Add task prompt if configured
        if self._definition and self._definition.task_prompt_template:
            task_content = self._render_template(
                self._definition.task_prompt_template,
                {**context.shared_state, **kwargs}
            )
            result.append(ChatMessage(
                role=MessageRole.SYSTEM,
                content=task_content,
            ))

        # Add conversation history
        result.extend(messages)

        # Add output instructions
        if self._definition and self._definition.output_instructions:
            result.append(ChatMessage(
                role=MessageRole.SYSTEM,
                content=self._definition.output_instructions,
            ))

        return result

    def _render_template(self, template: str, variables: Dict[str, Any]) -> str:
        """Render a prompt template with variables."""
        result = template

        # Simple variable interpolation: {{variable_name}}
        for key, value in variables.items():
            placeholder = f"{{{{{key}}}}}"
            if placeholder in result:
                result = result.replace(placeholder, str(value))

        return result

    def _get_tools_for_api(self) -> List[Dict[str, Any]]:
        """Convert built-in tools and system tools to OpenAI function calling format."""
        tools = []

        # Add custom built-in tools
        if self._definition and self._definition.builtin_tools:
            for tool_def in self._definition.builtin_tools:
                # Build parameter schema
                properties = {}
                required = []

                for param in tool_def.parameters:
                    param_schema = {
                        "type": param.type.value if hasattr(param.type, 'value') else str(param.type),
                        "description": param.description,
                    }
                    if param.enum:
                        param_schema["enum"] = param.enum
                    if param.default is not None:
                        param_schema["default"] = param.default

                    properties[param.name] = param_schema
                    if param.required:
                        required.append(param.name)

                tool = {
                    "type": "function",
                    "function": {
                        "name": tool_def.name,
                        "description": tool_def.description,
                        "parameters": {
                            "type": "object",
                            "properties": properties,
                            "required": required,
                        },
                    },
                }
                tools.append(tool)

        # Add enabled system tools
        if self._enabled_system_tools:
            system_tool_schemas = self._system_tool_registry.get_openai_schemas(
                self._enabled_system_tools
            )
            tools.extend(system_tool_schemas)

        return tools

    async def _execute_tool(
        self,
        tool_def: BuiltinToolDefinition,
        params: Dict[str, Any],
    ) -> str:
        """Execute a built-in tool."""
        try:
            if tool_def.tool_type == "http":
                return await self._execute_http_tool(tool_def, params)
            elif tool_def.tool_type == "code":
                return await self._execute_code_tool(tool_def, params)
            elif tool_def.tool_type == "transform":
                return await self._execute_transform_tool(tool_def, params)
            else:
                return f"Unknown tool type: {tool_def.tool_type}"
        except Exception as e:
            logger.error(f"Tool execution error: {e}")
            return f"Error executing tool: {str(e)}"

    async def _execute_http_tool(
        self,
        tool_def: BuiltinToolDefinition,
        params: Dict[str, Any],
    ) -> str:
        """Execute an HTTP API tool."""
        url = self._render_template(tool_def.http_url, params)
        headers = {
            k: self._render_template(v, params)
            for k, v in tool_def.http_headers.items()
        }

        body = None
        if tool_def.http_body_template:
            body = self._render_template(tool_def.http_body_template, params)
            try:
                body = json.loads(body)
            except json.JSONDecodeError:
                pass  # Keep as string

        async with aiohttp.ClientSession() as session:
            method = tool_def.http_method.upper()

            if method == "GET":
                async with session.get(url, headers=headers, timeout=tool_def.timeout) as resp:
                    return await resp.text()
            elif method == "POST":
                async with session.post(url, headers=headers, json=body, timeout=tool_def.timeout) as resp:
                    return await resp.text()
            elif method == "PUT":
                async with session.put(url, headers=headers, json=body, timeout=tool_def.timeout) as resp:
                    return await resp.text()
            elif method == "DELETE":
                async with session.delete(url, headers=headers, timeout=tool_def.timeout) as resp:
                    return await resp.text()
            else:
                return f"Unsupported HTTP method: {method}"

    async def _execute_code_tool(
        self,
        tool_def: BuiltinToolDefinition,
        params: Dict[str, Any],
    ) -> str:
        """Execute a code tool (sandboxed Python)."""
        if not tool_def.code:
            return "No code defined"

        # WARNING: In production, this should use a proper sandbox!
        # For now, we use a restricted exec
        try:
            # Create restricted globals
            safe_globals = {
                "__builtins__": {
                    "len": len,
                    "str": str,
                    "int": int,
                    "float": float,
                    "list": list,
                    "dict": dict,
                    "bool": bool,
                    "range": range,
                    "enumerate": enumerate,
                    "zip": zip,
                    "map": map,
                    "filter": filter,
                    "sorted": sorted,
                    "sum": sum,
                    "min": min,
                    "max": max,
                    "abs": abs,
                    "round": round,
                    "print": print,
                },
                "json": json,
                "re": re,
            }

            # Add parameters
            local_vars = {"params": params, "result": None}

            # Execute code
            exec(tool_def.code, safe_globals, local_vars)

            return str(local_vars.get("result", "No result"))

        except Exception as e:
            return f"Code execution error: {str(e)}"

    async def _execute_transform_tool(
        self,
        tool_def: BuiltinToolDefinition,
        params: Dict[str, Any],
    ) -> str:
        """Execute a data transformation tool."""
        result = {}

        if tool_def.output_mapping:
            for output_key, input_expr in tool_def.output_mapping.items():
                # Simple expression evaluation
                if input_expr in params:
                    result[output_key] = params[input_expr]
                else:
                    result[output_key] = self._render_template(input_expr, params)

        return json.dumps(result)

    async def _handle_tool_calls(
        self,
        response: AgentResponse,
        messages: List[ChatMessage],
        context: ExecutionContext,
    ) -> AgentResponse:
        """Handle tool calls in the response."""
        from ..core.models import ToolResult

        tool_results = []

        for tool_call in response.tool_calls:
            # First check if it's a custom built-in tool
            tool_def = self._tools_registry.get(tool_call.name)
            if tool_def:
                result = await self._execute_tool(tool_def, tool_call.arguments)
                tool_results.append(ToolResult(
                    tool_call_id=tool_call.id,
                    content=result,
                    is_error=False,
                ))
            # Then check if it's a system tool
            elif tool_call.name in self._enabled_system_tools:
                system_tool = self._system_tool_registry.get(tool_call.name)
                if system_tool:
                    try:
                        result = await system_tool.execute(**tool_call.arguments)
                        tool_results.append(ToolResult(
                            tool_call_id=tool_call.id,
                            content=result,
                            is_error=False,
                        ))
                    except Exception as e:
                        logger.error(f"System tool execution error: {e}")
                        tool_results.append(ToolResult(
                            tool_call_id=tool_call.id,
                            content=f"Error executing system tool: {str(e)}",
                            is_error=True,
                        ))
                else:
                    tool_results.append(ToolResult(
                        tool_call_id=tool_call.id,
                        content=f"System tool not found: {tool_call.name}",
                        is_error=True,
                    ))
            else:
                tool_results.append(ToolResult(
                    tool_call_id=tool_call.id,
                    content=f"Unknown tool: {tool_call.name}",
                    is_error=True,
                ))

        response.tool_results = tool_results
        return response

    def _format_output(self, response: AgentResponse) -> AgentResponse:
        """Format output according to output format configuration."""
        if not self._definition or not self._definition.output_format:
            return response

        format_type = self._definition.output_format.format_type

        if format_type == "json" and response.messages:
            # Try to parse and validate JSON
            content = response.messages[-1].content
            try:
                parsed = json.loads(content)
                response.messages[-1].content = json.dumps(parsed, indent=2, ensure_ascii=False)
            except json.JSONDecodeError:
                # Leave as is
                pass

        return response

    def _convert_to_openai_messages(self, messages: List[ChatMessage]) -> List[Dict[str, str]]:
        """Convert our ChatMessage to OpenAI format."""
        openai_messages = []
        for msg in messages:
            role = "system" if msg.role == MessageRole.SYSTEM else \
                   "user" if msg.role == MessageRole.USER else "assistant"
            openai_messages.append({
                "role": role,
                "content": msg.content,
            })
        return openai_messages

    def _convert_from_openai_response(self, response: Any) -> AgentResponse:
        """Convert OpenAI response to our format."""
        from ..core.models import ToolCall

        messages = []
        tool_calls = []

        if response.choices:
            choice = response.choices[0]
            msg = choice.message

            # Extract content
            if msg.content:
                messages.append(ChatMessage(
                    role=MessageRole.ASSISTANT,
                    content=msg.content,
                    name=self.node.name,
                ))

            # Extract tool calls
            if hasattr(msg, 'tool_calls') and msg.tool_calls:
                for tc in msg.tool_calls:
                    arguments = {}
                    if tc.function.arguments:
                        try:
                            arguments = json.loads(tc.function.arguments)
                        except json.JSONDecodeError:
                            arguments = {"raw": tc.function.arguments}

                    tool_calls.append(ToolCall(
                        id=tc.id,
                        name=tc.function.name,
                        arguments=arguments,
                    ))

        # If no content but tool calls, add placeholder
        if not messages and tool_calls:
            messages.append(ChatMessage(
                role=MessageRole.ASSISTANT,
                content="",
                name=self.node.name,
            ))

        return AgentResponse(
            messages=messages,
            tool_calls=tool_calls,
            response_id=response.id if hasattr(response, 'id') else str(uuid4()),
            metadata={
                "model": response.model if hasattr(response, 'model') else None,
                "usage": response.usage.model_dump() if hasattr(response, 'usage') and response.usage else None,
            },
        )

    def _create_fallback_response(self, messages: List[ChatMessage]) -> AgentResponse:
        """Create fallback response when chat client is not available."""
        return AgentResponse(
            messages=[ChatMessage(
                role=MessageRole.ASSISTANT,
                content=f"[{self.node.name}]: Chat client not available. Please check API configuration.",
                name=self.node.name,
            )],
            response_id=str(uuid4()),
            metadata={"fallback": True},
        )


# Register the adapter
AdapterFactory.register(AgentType.BUILTIN, BuiltinAgentAdapter)
