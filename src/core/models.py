"""
Core data models for Proton agent orchestration platform.
"""

from enum import Enum
from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, Field
from datetime import datetime


class AgentType(str, Enum):
    """Supported agent types."""
    NATIVE = "native"          # Built with agent-framework directly
    BUILTIN = "builtin"        # Built-in agent with visual editing
    COZE = "coze"              # Coze platform agent
    DIFY = "dify"              # Dify platform agent
    DOUBAO = "doubao"          # Doubao (豆包) platform agent
    AUTOGEN = "autogen"        # AutoGen framework agent
    WORKFLOW = "workflow"      # Reference to another workflow (inter-calling)
    CUSTOM = "custom"          # Custom adapter


class RoutingStrategy(str, Enum):
    """Strategies for routing messages to child agents."""
    SEQUENTIAL = "sequential"          # Execute children one by one
    PARALLEL = "parallel"              # Execute all children in parallel
    CONDITIONAL = "conditional"        # Route based on classifier
    HANDOFF = "handoff"                # Transfer control between agents
    HIERARCHICAL = "hierarchical"      # Decompose and aggregate
    ROUND_ROBIN = "round_robin"        # Distribute evenly
    LOAD_BALANCED = "load_balanced"    # Based on agent load
    COORDINATOR = "coordinator"        # Coordinator pattern: parent → children → parent integrates


class ExecutionMode(str, Enum):
    """Workflow execution modes."""
    SYNC = "sync"
    ASYNC = "async"
    STREAMING = "streaming"


class ErrorHandlingStrategy(str, Enum):
    """How to handle errors during execution."""
    FAIL_FAST = "fail_fast"                # Stop on first error
    CONTINUE = "continue"                   # Skip failed agents, continue others
    RETRY = "retry"                         # Retry failed agents
    FALLBACK = "fallback"                   # Use fallback agent


# ============== Plugin Configurations ==============

class MCPServerConfig(BaseModel):
    """Configuration for MCP server connection."""
    name: str
    command: str                            # Command to start MCP server
    args: List[str] = Field(default_factory=list)
    env: Dict[str, str] = Field(default_factory=dict)
    transport: str = "stdio"                # stdio, http, websocket
    url: Optional[str] = None               # For http/websocket transport


class SkillConfig(BaseModel):
    """Configuration for a skill."""
    name: str
    description: str
    module_path: str                        # Python module path
    function_name: str                      # Function name in module
    parameters_schema: Optional[Dict[str, Any]] = None
    approval_required: bool = False


# ============== Built-in Tool Definitions ==============

class ToolParameterType(str, Enum):
    """Parameter types for built-in tools."""
    STRING = "string"
    INTEGER = "integer"
    NUMBER = "number"
    BOOLEAN = "boolean"
    ARRAY = "array"
    OBJECT = "object"


class ToolParameter(BaseModel):
    """Definition of a tool parameter."""
    name: str
    type: ToolParameterType = ToolParameterType.STRING
    description: str = ""
    required: bool = True
    default: Optional[Any] = None
    enum: Optional[List[str]] = None  # For string type with choices
    items_type: Optional[ToolParameterType] = None  # For array type


class BuiltinToolDefinition(BaseModel):
    """
    Definition for a built-in tool that can be created in the UI.

    Built-in tools can be:
    - HTTP API calls
    - Code execution (sandboxed)
    - Data transformations
    - Custom logic
    """
    name: str
    description: str
    tool_type: str = "http"  # http, code, transform, composite
    parameters: List[ToolParameter] = Field(default_factory=list)

    # For HTTP tools
    http_method: str = "GET"
    http_url: str = ""
    http_headers: Dict[str, str] = Field(default_factory=dict)
    http_body_template: Optional[str] = None  # JSON template with {{param}} placeholders

    # For code tools (Python code executed in sandbox)
    code: Optional[str] = None
    code_language: str = "python"

    # For transform tools
    input_mapping: Optional[Dict[str, str]] = None
    output_mapping: Optional[Dict[str, str]] = None

    # Execution settings
    timeout: float = 30.0
    retry_count: int = 0
    approval_required: bool = False


# ============== Prompt Template System ==============

class PromptVariable(BaseModel):
    """A variable that can be used in prompt templates."""
    name: str
    description: str = ""
    type: ToolParameterType = ToolParameterType.STRING
    default: Optional[str] = None
    required: bool = False


class PromptTemplate(BaseModel):
    """
    A reusable prompt template with variables.

    Templates support:
    - Variable interpolation: {{variable_name}}
    - Conditional sections: {% if condition %}...{% endif %}
    - Loops: {% for item in items %}...{% endfor %}
    """
    name: str
    description: str = ""
    template: str  # The actual prompt template
    variables: List[PromptVariable] = Field(default_factory=list)
    category: str = "general"  # general, system, task, output


class OutputFormat(BaseModel):
    """Defines expected output format from an agent."""
    format_type: str = "text"  # text, json, markdown, structured
    json_schema: Optional[Dict[str, Any]] = None  # For json format
    structured_fields: Optional[List[Dict[str, Any]]] = None  # For structured format
    example: Optional[str] = None


# ============== Built-in Agent Definition ==============

class BuiltinAgentDefinition(BaseModel):
    """
    Complete definition for a built-in agent that can be visually edited.

    This represents an agent that is fully configured within the platform,
    not relying on external services like Coze or Dify.
    """
    # Basic info
    name: str
    description: str = ""
    avatar: Optional[str] = None  # URL or base64 image
    category: str = "general"  # general, assistant, specialist, router

    # Model configuration
    provider: str = "openai"  # openai, azure, anthropic, ollama, local
    model: str = "gpt-4"
    base_url: Optional[str] = None  # Custom API base URL
    api_key: Optional[str] = None  # API key (stored securely)
    temperature: float = 0.7
    max_tokens: int = 4096
    top_p: float = 1.0
    frequency_penalty: float = 0.0
    presence_penalty: float = 0.0

    # Prompts
    system_prompt: str = ""
    task_prompt_template: Optional[str] = None
    output_instructions: Optional[str] = None

    # Prompt templates (reusable)
    prompt_templates: List[PromptTemplate] = Field(default_factory=list)

    # Output format
    output_format: Optional[OutputFormat] = None

    # Built-in tools
    builtin_tools: List[BuiltinToolDefinition] = Field(default_factory=list)

    # System tools (file, shell, web operations)
    system_tools: List[str] = Field(default_factory=list)  # List of enabled system tool names

    # Knowledge/Context
    knowledge_base: Optional[str] = None  # RAG source reference
    context_window_strategy: str = "sliding"  # sliding, summary, full
    max_context_messages: int = 20

    # Behavior settings
    streaming_enabled: bool = True
    tool_choice: str = "auto"  # auto, none, required
    parallel_tool_calls: bool = True

    # Safety settings
    content_filter_enabled: bool = True
    max_output_tokens: int = 4096

    # Metadata
    tags: List[str] = Field(default_factory=list)
    version: str = "1.0.0"
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)


# ============== Agent Template (for quick creation) ==============

class AgentTemplate(BaseModel):
    """
    Pre-defined agent template for quick creation.

    Templates provide starting points for common agent types.
    """
    id: str
    name: str
    description: str
    category: str
    icon: str = ""
    preview_image: Optional[str] = None

    # The actual agent definition
    definition: BuiltinAgentDefinition

    # Template metadata
    popularity: int = 0
    is_official: bool = False
    author: str = "system"


class RAGSourceConfig(BaseModel):
    """Configuration for RAG data source."""
    name: str
    type: str                               # vector_db, file, api
    connection_string: Optional[str] = None
    collection_name: Optional[str] = None
    embedding_model: str = "text-embedding-ada-002"
    chunk_size: int = 1000
    chunk_overlap: int = 200
    top_k: int = 5


class PluginConfig(BaseModel):
    """Unified plugin configuration."""
    type: str                               # mcp, skill, rag
    enabled: bool = True
    mcp_config: Optional[MCPServerConfig] = None
    skill_config: Optional[SkillConfig] = None
    rag_config: Optional[RAGSourceConfig] = None


# ============== Agent Configurations ==============

class RetryPolicy(BaseModel):
    """Retry policy for agent execution."""
    max_retries: int = 3
    initial_delay: float = 1.0              # seconds
    max_delay: float = 60.0                 # seconds
    exponential_base: float = 2.0
    retry_on_errors: List[str] = Field(
        default_factory=lambda: ["timeout", "rate_limit", "server_error"]
    )


class NativeAgentConfig(BaseModel):
    """Configuration for native agent-framework agents."""
    instructions: str
    model: str = "gpt-4"
    provider: str = "openai"                # openai, azure, anthropic
    temperature: float = 0.7
    max_tokens: int = 4096
    # Provider-specific settings
    azure_endpoint: Optional[str] = None
    azure_deployment: Optional[str] = None
    api_key: Optional[str] = None


class CozeConfig(BaseModel):
    """Configuration for Coze platform agents."""
    bot_id: str
    api_key: str
    api_base: str = "https://api.coze.com"
    conversation_id: Optional[str] = None
    user_id: str = "default_user"


class DifyConfig(BaseModel):
    """Configuration for Dify platform agents."""
    app_id: str
    api_key: str
    api_base: str = "https://api.dify.ai/v1"
    mode: str = "chat"                      # chat, completion, workflow
    user_id: str = "default_user"
    conversation_id: Optional[str] = None


class DoubaoConfig(BaseModel):
    """Configuration for Doubao (豆包) platform agents."""
    bot_id: str
    api_key: str
    api_base: str = "https://api.doubao.com"
    model: str = "doubao-pro"
    user_id: str = "default_user"


class AutoGenConfig(BaseModel):
    """Configuration for AutoGen framework agents."""
    agent_class: str                        # Full class path
    config_list: List[Dict[str, Any]] = Field(default_factory=list)
    system_message: Optional[str] = None
    human_input_mode: str = "NEVER"         # NEVER, ALWAYS, TERMINATE
    max_consecutive_auto_reply: int = 10


class WorkflowReferenceConfig(BaseModel):
    """Configuration for workflow-type agents that reference other workflows."""
    workflow_id: str                        # Referenced workflow ID
    input_mapping: Dict[str, str] = Field(default_factory=dict)   # Map parent context to child input
    output_mapping: Dict[str, str] = Field(default_factory=dict)  # Map child output to parent context


class AgentConfig(BaseModel):
    """Unified agent configuration."""
    # Common settings
    model: str = "gpt-4"
    temperature: float = 0.7
    max_tokens: int = 4096

    # Type-specific configurations
    native_config: Optional[NativeAgentConfig] = None
    coze_config: Optional[CozeConfig] = None
    dify_config: Optional[DifyConfig] = None
    doubao_config: Optional[DoubaoConfig] = None
    autogen_config: Optional[AutoGenConfig] = None
    workflow_config: Optional[WorkflowReferenceConfig] = None  # For WORKFLOW type

    # Built-in agent definition (for visual editing)
    builtin_definition: Optional[BuiltinAgentDefinition] = None

    # Plugins
    mcp_servers: List[MCPServerConfig] = Field(default_factory=list)
    skills: List[SkillConfig] = Field(default_factory=list)
    rag_sources: List[RAGSourceConfig] = Field(default_factory=list)


class AgentCapabilities(BaseModel):
    """Describes what an agent can do."""
    supports_streaming: bool = True
    supports_tools: bool = True
    supports_vision: bool = False
    supports_audio: bool = False
    supports_files: bool = False
    max_context_length: int = 128000
    supported_languages: List[str] = Field(default_factory=lambda: ["en", "zh"])


# ============== Message Types ==============

class MessageRole(str, Enum):
    """Message roles."""
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    TOOL = "tool"


class ChatMessage(BaseModel):
    """A chat message."""
    role: MessageRole
    content: str
    name: Optional[str] = None
    tool_call_id: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.now)


class ToolCall(BaseModel):
    """A tool call request."""
    id: str
    name: str
    arguments: Dict[str, Any]


class ToolResult(BaseModel):
    """Result from a tool call."""
    tool_call_id: str
    content: str
    is_error: bool = False


class AgentResponse(BaseModel):
    """Response from an agent execution."""
    messages: List[ChatMessage]
    tool_calls: List[ToolCall] = Field(default_factory=list)
    tool_results: List[ToolResult] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    usage: Optional[Dict[str, int]] = None
    response_id: str = ""


class AgentResponseUpdate(BaseModel):
    """Streaming update from agent execution."""
    delta_content: str = ""
    tool_call: Optional[ToolCall] = None
    is_complete: bool = False
    metadata: Dict[str, Any] = Field(default_factory=dict)


# ============== Execution Event Types ==============

class ExecutionEventType(str, Enum):
    """Types of events emitted during workflow execution."""
    WORKFLOW_START = "workflow_start"
    WORKFLOW_COMPLETE = "workflow_complete"
    WORKFLOW_ERROR = "workflow_error"
    NODE_START = "node_start"
    NODE_THINKING = "node_thinking"
    NODE_TOOL_CALL = "node_tool_call"
    NODE_TOOL_RESULT = "node_tool_result"
    NODE_COMPLETE = "node_complete"
    NODE_ERROR = "node_error"
    ROUTING_START = "routing_start"


class ExecutionEvent(BaseModel):
    """Event emitted during workflow execution for real-time visualization."""
    event_type: ExecutionEventType
    timestamp: float
    workflow_id: str
    execution_id: str
    node_id: Optional[str] = None
    node_name: Optional[str] = None
    depth: int = 0
    content: Optional[str] = None
    delta_content: Optional[str] = None
    tool_call: Optional[ToolCall] = None
    tool_result: Optional[ToolResult] = None
    routing_strategy: Optional[str] = None
    target_nodes: Optional[List[str]] = None
    status: Optional[str] = None
    error: Optional[str] = None
    duration_ms: Optional[float] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


# ============== Workflow Configuration ==============

class WorkflowPublishConfig(BaseModel):
    """Configuration for published workflows."""
    published: bool = False
    version: str = "1.0.0"
    api_key: Optional[str] = None         # Generated API key for access
    rate_limit: int = 100                 # Requests per minute
    description: str = ""
    tags: List[str] = Field(default_factory=list)
    published_at: Optional[datetime] = None


class WorkflowConfig(BaseModel):
    """Configuration for a workflow."""
    id: str
    name: str
    description: str = ""

    # Tree structure
    root_agent_id: str

    # Global settings
    global_context: Dict[str, Any] = Field(default_factory=dict)
    max_total_depth: int = 10
    total_timeout: float = 300.0

    # Execution settings
    execution_mode: ExecutionMode = ExecutionMode.ASYNC
    error_handling: ErrorHandlingStrategy = ErrorHandlingStrategy.FAIL_FAST

    # Publishing settings
    publish_config: Optional[WorkflowPublishConfig] = None

    # Metadata
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    version: str = "1.0.0"


# ============== Copilot Session Models ==============

class CopilotMessage(BaseModel):
    """A message in copilot conversation."""
    role: str  # user, assistant, tool
    content: str
    tool_calls: Optional[List[Dict[str, Any]]] = None
    tool_results: Optional[List[Dict[str, Any]]] = None
    timestamp: datetime = Field(default_factory=datetime.now)


class CopilotSession(BaseModel):
    """Session for multi-turn copilot conversation."""
    session_id: str
    workflow_id: Optional[str] = None     # Generated workflow ID
    messages: List[CopilotMessage] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class CopilotEventType(str, Enum):
    """Types of events emitted during copilot conversation."""
    CONTENT = "content"           # Text content delta
    TOOL_START = "tool_start"     # Tool execution started
    TOOL_RESULT = "tool_result"   # Tool execution completed
    WORKFLOW_CREATED = "workflow_created"  # New workflow generated
    WORKFLOW_UPDATED = "workflow_updated"  # Existing workflow modified
    COMPLETE = "complete"         # Conversation turn complete
    ERROR = "error"               # Error occurred


class CopilotEvent(BaseModel):
    """Event emitted during copilot conversation."""
    type: CopilotEventType
    delta: Optional[str] = None           # For content delta
    tool_name: Optional[str] = None       # For tool events
    tool_args: Optional[Dict[str, Any]] = None  # For tool_start
    result: Optional[Dict[str, Any]] = None     # For tool_result
    workflow_id: Optional[str] = None     # For workflow events
    error: Optional[str] = None           # For error events
    timestamp: datetime = Field(default_factory=datetime.now)
