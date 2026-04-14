"""
FastAPI application for Proton Agent Platform.

Provides REST API for:
- Agent management
- Workflow orchestration
- Plugin management
- Real-time execution
"""

import logging
import json
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Dict, List, Optional

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
import uvicorn

from ..core.models import (
    AgentType,
    AgentConfig,
    RoutingStrategy,
    MCPServerConfig,
    SkillConfig,
    RAGSourceConfig,
    BuiltinAgentDefinition,
    BuiltinToolDefinition,
    ToolParameter,
    ToolParameterType,
    PromptTemplate,
    PromptVariable,
    OutputFormat,
    AgentTemplate,
    InstalledSkill,
    ArtifactCandidateStatus,
    ArtifactRolloutStatus,
)
from ..governance import ApprovalRecord, ApprovalStatus, get_approval_service
from ..core.agent_node import AgentNode
from ..orchestration.workflow import (
    Workflow,
    WorkflowManager,
    WorkflowResult,
    WorkflowState,
    get_workflow_manager,
)
from ..plugins.registry import get_plugin_registry
from ..plugins.skill_manager import get_skill_manager
from fastapi import UploadFile, File

logger = logging.getLogger(__name__)


# ============== Request/Response Models ==============

class CreateAgentRequest(BaseModel):
    """Request to create an agent."""
    name: str
    description: str = ""
    type: AgentType = AgentType.NATIVE
    config: AgentConfig = Field(default_factory=AgentConfig)
    parent_id: Optional[str] = None
    routing_strategy: RoutingStrategy = RoutingStrategy.SEQUENTIAL
    max_depth: int = 5
    timeout: float = 60.0


class UpdateAgentRequest(BaseModel):
    """Request to update an agent."""
    name: Optional[str] = None
    description: Optional[str] = None
    config: Optional[AgentConfig] = None
    routing_strategy: Optional[RoutingStrategy] = None
    enabled: Optional[bool] = None


class AgentResponse(BaseModel):
    """Agent response model."""
    id: str
    name: str
    description: str
    type: str
    parent_id: Optional[str]
    children: List[str]
    enabled: bool


class CreateWorkflowRequest(BaseModel):
    """Request to create a workflow."""
    name: str
    description: str = ""
    root_agent: Optional[CreateAgentRequest] = None


class RunWorkflowRequest(BaseModel):
    """Request to run a workflow."""
    message: str
    stream: bool = False


class WorkflowResponse(BaseModel):
    """Workflow response model."""
    id: str
    name: str
    description: str
    state: str
    agent_count: int
    created_at: str
    updated_at: str


class ExecutionResponse(BaseModel):
    """Execution result response."""
    workflow_id: str
    execution_id: str
    state: str
    output: Optional[str] = None
    error: Optional[str] = None
    duration_ms: Optional[float] = None


class RegisterMCPRequest(BaseModel):
    """Request to register an MCP server."""
    name: str
    command: str
    args: List[str] = Field(default_factory=list)
    env: Dict[str, str] = Field(default_factory=dict)
    agent_id: Optional[str] = None
    is_global: bool = False


class RegisterSkillRequest(BaseModel):
    """Request to register a skill."""
    name: str
    description: str
    module_path: str
    function_name: str
    agent_id: Optional[str] = None


class RegisterRAGRequest(BaseModel):
    """Request to register a RAG source."""
    name: str
    type: str = "vector_db"
    connection_string: Optional[str] = None
    collection_name: Optional[str] = None
    agent_id: Optional[str] = None


class CopilotChatRequest(BaseModel):
    """Request to chat with Copilot."""
    session_id: str
    message: str
    stream: bool = True


class CopilotConfigRequest(BaseModel):
    """Request to configure Copilot service."""
    provider: Optional[str] = None
    model: Optional[str] = None
    api_key: Optional[str] = None
    base_url: Optional[str] = None


class SearchConfigRequest(BaseModel):
    """Request to configure search providers."""
    provider: Optional[str] = None  # Default search provider
    searxng_base_url: Optional[str] = None
    serper_api_key: Optional[str] = None
    brave_api_key: Optional[str] = None
    bing_api_key: Optional[str] = None
    tavily_api_key: Optional[str] = None
    google_api_key: Optional[str] = None
    google_cx: Optional[str] = None


class EmailConfigRequest(BaseModel):
    """Request to configure email sending."""
    preferred_method: Optional[str] = None  # "auto", "resend", "smtp"
    resend_api_key: Optional[str] = None
    resend_from: Optional[str] = None
    smtp_host: Optional[str] = None
    smtp_port: Optional[int] = None
    smtp_user: Optional[str] = None
    smtp_password: Optional[str] = None
    smtp_from: Optional[str] = None
    smtp_use_tls: Optional[bool] = None


class TestEmailRequest(BaseModel):
    """Request to test email sending."""
    to: str


class PublishRequest(BaseModel):
    """Request to publish a workflow."""
    version: str = "1.0.0"
    description: str = ""
    tags: List[str] = Field(default_factory=list)


class CreateApprovalRequest(BaseModel):
    """Request to create an approval entry."""

    workflow_id: Optional[str] = None
    execution_id: Optional[str] = None
    node_id: Optional[str] = None
    node_name: Optional[str] = None
    tool_call_id: str
    tool_name: str
    tool_source: str = "manual"
    arguments: Dict[str, Any] = Field(default_factory=dict)
    approval_required: bool = True
    is_dangerous: bool = False
    reason: Optional[str] = None
    requested_by: Optional[str] = None


class ResolveApprovalRequest(BaseModel):
    """Request to resolve an approval entry."""

    actor: Optional[str] = None
    comment: Optional[str] = None


class GatewayRequest(BaseModel):
    """Request for the gateway router."""
    message: str
    stream: bool = True
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ArtifactDecisionRequest(BaseModel):
    user_id: str = "default"
    source_session_id: Optional[str] = None
    parent_candidate_id: Optional[str] = None
    task_summary: str
    repeat_count: int = 1
    tool_call_count: int = 0
    unique_tool_count: int = 0
    parallel_branches: int = 0
    requires_long_running: bool = False
    has_manual_steps: bool = False
    failure_rate: float = 0.0
    high_risk: bool = False
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ArtifactDecisionFromTrajectoryRequest(BaseModel):
    user_id: str = "default"
    session_id: str
    tool_execution_audit: List[Dict[str, Any]] = Field(default_factory=list)
    approval_results: List[Dict[str, Any]] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ArtifactApproveRequest(BaseModel):
    approver: str = "system"
    bind_agent_id: Optional[str] = None


class ArtifactMetricsCollectRequest(BaseModel):
    reporter: str = "system"
    metrics: Dict[str, Any] = Field(default_factory=dict)


class ArtifactRolloutDecisionRequest(BaseModel):
    min_sample_size: int = 20
    upgrade_success_rate: float = 0.97
    rollback_error_rate: float = 0.08
    max_latency_p95_ms: float = 2500.0
    min_success_rate_for_rollback: float = 0.85
    auto_apply: bool = False
    operator: str = "system"


class ArtifactRolloutTransitionRequest(BaseModel):
    target_status: ArtifactRolloutStatus
    operator: str = "system"
    reason: Optional[str] = None
    freeze_window_minutes: Optional[int] = None
    manual_override: bool = False
    override_reason: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ArtifactABRoutingConfigRequest(BaseModel):
    enabled: bool = True
    control_ratio: float = 0.5
    salt: str = ""
    operator: str = "system"
    notes: Optional[str] = None


class ArtifactABRoutingRouteRequest(BaseModel):
    subject_key: str
    force_bucket: Optional[str] = None
    force_target_candidate_id: Optional[str] = None


class ArtifactRollbackFreezeOverrideRequest(BaseModel):
    operator: str = "system"
    reason: str = "manual_override"


class ArtifactPeriodicLearningRequest(BaseModel):
    user_id: Optional[str] = None
    min_cluster_size: int = 2
    max_sessions: int = 200
    trigger_revision: bool = True
    min_revision_samples: int = 12
    revision_cooldown_hours: int = 24
    dry_run: bool = False


# ============== Application ==============

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    # Startup
    logger.info("Starting Proton Agent Platform...")

    # Initialize storage
    from ..storage import initialize_storage
    storage = await initialize_storage()
    logger.info("Storage initialized")

    # Load configurations from database
    logger.info("Loading configurations from database...")
    try:
        from ..tools.email import EmailConfig
        from ..tools.web import SearchConfig
        from ..copilot import get_copilot_service

        # Initialize email config
        await EmailConfig.initialize_from_storage()
        logger.info("Email configuration loaded")

        # Initialize search config
        await SearchConfig.initialize_from_storage()
        logger.info("Search configuration loaded")

        # Initialize copilot config
        copilot = get_copilot_service()
        await copilot.load_from_storage()
        logger.info("Copilot configuration loaded")
    except Exception as e:
        logger.warning(f"Failed to load some configurations: {e}")

    # Pre-load workflows
    manager = get_workflow_manager()
    await manager._ensure_storage()

    # Pre-load portals
    try:
        from ..portal import get_portal_manager
        portal_mgr = get_portal_manager()
        await portal_mgr._ensure_ready()
        # Ensure default Root Portal exists
        await portal_mgr.ensure_default_portal()
        logger.info("Portal manager initialized (default portal ensured)")
    except Exception as e:
        logger.warning(f"Failed to initialize portal manager: {e}")

    yield

    # Shutdown
    logger.info("Shutting down Proton Agent Platform...")
    plugin_registry = get_plugin_registry()
    await plugin_registry.cleanup_all()

    # Close storage
    await storage.close()


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="Proton Agent Platform",
        description="Tree-based Agent Orchestration Platform",
        version="0.1.0",
        lifespan=lifespan,
    )

    # CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ============== Health Check ==============

    @app.get("/health")
    async def health_check():
        """Health check endpoint."""
        return {"status": "healthy", "version": "0.1.0"}

    # ============== Approval Endpoints ==============

    @app.post("/api/approvals", response_model=ApprovalRecord, status_code=201)
    async def create_approval(request: CreateApprovalRequest):
        """Create an approval request manually or for integration tests."""
        approval_service = get_approval_service()
        approval = ApprovalRecord(
            workflow_id=request.workflow_id,
            execution_id=request.execution_id,
            node_id=request.node_id,
            node_name=request.node_name,
            tool_call_id=request.tool_call_id,
            tool_name=request.tool_name,
            tool_source=request.tool_source,
            arguments=request.arguments,
            approval_required=request.approval_required,
            is_dangerous=request.is_dangerous,
            reason=request.reason,
            requested_by=request.requested_by,
        )
        return await approval_service.create_approval(approval)

    @app.get("/api/approvals", response_model=List[ApprovalRecord])
    async def list_approvals(
        status: Optional[ApprovalStatus] = None,
        workflow_id: Optional[str] = None,
        execution_id: Optional[str] = None,
        tool_name: Optional[str] = None,
    ):
        """List persisted approval requests."""
        approval_service = get_approval_service()
        return await approval_service.list_approvals(
            status=status,
            workflow_id=workflow_id,
            execution_id=execution_id,
            tool_name=tool_name,
        )

    @app.get("/api/approvals/{approval_id}", response_model=ApprovalRecord)
    async def get_approval(approval_id: str):
        """Get a single approval request."""
        approval_service = get_approval_service()
        approval = await approval_service.get_approval(approval_id)
        if approval is None:
            raise HTTPException(status_code=404, detail="Approval not found")
        return approval

    @app.post("/api/approvals/{approval_id}/approve", response_model=ApprovalRecord)
    async def approve_approval(approval_id: str, request: ResolveApprovalRequest):
        """Approve a pending approval request."""
        approval_service = get_approval_service()
        try:
            return await approval_service.resolve_approval(
                approval_id,
                approved=True,
                actor=request.actor,
                comment=request.comment,
            )
        except KeyError:
            raise HTTPException(status_code=404, detail="Approval not found")
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc))

    @app.post("/api/approvals/{approval_id}/deny", response_model=ApprovalRecord)
    async def deny_approval(approval_id: str, request: ResolveApprovalRequest):
        """Deny a pending approval request."""
        approval_service = get_approval_service()
        try:
            return await approval_service.resolve_approval(
                approval_id,
                approved=False,
                actor=request.actor,
                comment=request.comment,
            )
        except KeyError:
            raise HTTPException(status_code=404, detail="Approval not found")
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc))

    # ============== Workflow Endpoints ==============

    @app.post("/api/workflows", response_model=WorkflowResponse)
    async def create_workflow(request: CreateWorkflowRequest):
        """Create a new workflow."""
        manager = get_workflow_manager()

        root_agent = None
        if request.root_agent:
            root_agent = AgentNode(
                name=request.root_agent.name,
                description=request.root_agent.description,
                type=request.root_agent.type,
                config=request.root_agent.config,
                routing_strategy=request.root_agent.routing_strategy,
                max_depth=request.root_agent.max_depth,
                timeout=request.root_agent.timeout,
            )

        workflow = await manager.create_workflow(
            name=request.name,
            description=request.description,
            root_agent=root_agent,
        )

        return WorkflowResponse(
            id=workflow.id,
            name=workflow.name,
            description=workflow.description,
            state=workflow.state.value,
            agent_count=len(workflow.tree),
            created_at=workflow.created_at.isoformat(),
            updated_at=workflow.updated_at.isoformat(),
        )

    @app.get("/api/workflows", response_model=List[WorkflowResponse])
    async def list_workflows():
        """List all workflows."""
        manager = get_workflow_manager()
        workflows = await manager.list_workflows()

        return [
            WorkflowResponse(
                id=w.id,
                name=w.name,
                description=w.description,
                state=w.state.value,
                agent_count=len(w.tree),
                created_at=w.created_at.isoformat(),
                updated_at=w.updated_at.isoformat(),
            )
            for w in workflows
        ]

    @app.get("/api/workflows/{workflow_id}", response_model=Dict[str, Any])
    async def get_workflow(workflow_id: str):
        """Get workflow details."""
        manager = get_workflow_manager()
        workflow = await manager.get_workflow(workflow_id)

        if not workflow:
            raise HTTPException(status_code=404, detail="Workflow not found")

        return workflow.to_dict()

    @app.delete("/api/workflows/{workflow_id}")
    async def delete_workflow(workflow_id: str):
        """Delete a workflow."""
        manager = get_workflow_manager()
        deleted = await manager.delete_workflow(workflow_id)

        if not deleted:
            raise HTTPException(status_code=404, detail="Workflow not found")

        return {"status": "deleted", "id": workflow_id}

    @app.post("/api/workflows/{workflow_id}/run")
    async def run_workflow(workflow_id: str, request: RunWorkflowRequest):
        """Run a workflow."""
        manager = get_workflow_manager()

        if request.stream:
            # Return ExecutionEvent SSE stream
            async def generate():
                async for event in manager.run_workflow_stream_events(
                    workflow_id, request.message
                ):
                    event_data = event.model_dump(exclude_none=True)
                    yield f"data: {json.dumps(event_data, ensure_ascii=False)}\n\n"
                yield "data: [DONE]\n\n"

            return StreamingResponse(
                generate(),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no",
                },
            )

        result = await manager.run_workflow(workflow_id, request.message)

        output = None
        if result.response and result.response.messages:
            output = "\n".join(m.content for m in result.response.messages)

        return ExecutionResponse(
            workflow_id=result.workflow_id,
            execution_id=result.execution_id,
            state=result.state.value,
            output=output,
            error=result.error,
            duration_ms=result.duration_ms,
        )

    # ============== Agent Endpoints ==============

    @app.post("/api/workflows/{workflow_id}/agents", response_model=AgentResponse)
    async def add_agent(workflow_id: str, request: CreateAgentRequest):
        """Add an agent to a workflow."""
        manager = get_workflow_manager()
        workflow = await manager.get_workflow(workflow_id)

        if not workflow:
            raise HTTPException(status_code=404, detail="Workflow not found")

        node = AgentNode(
            name=request.name,
            description=request.description,
            type=request.type,
            config=request.config,
            parent_id=request.parent_id,
            routing_strategy=request.routing_strategy,
            max_depth=request.max_depth,
            timeout=request.timeout,
        )

        workflow.add_agent(node, request.parent_id)

        # Persist changes
        await manager.save_current_state(workflow_id)

        return AgentResponse(
            id=node.id,
            name=node.name,
            description=node.description,
            type=node.type.value,
            parent_id=node.parent_id,
            children=node.children,
            enabled=node.enabled,
        )

    @app.get("/api/workflows/{workflow_id}/agents", response_model=List[AgentResponse])
    async def list_agents(workflow_id: str):
        """List all agents in a workflow."""
        manager = get_workflow_manager()
        workflow = await manager.get_workflow(workflow_id)

        if not workflow:
            raise HTTPException(status_code=404, detail="Workflow not found")

        return [
            AgentResponse(
                id=node.id,
                name=node.name,
                description=node.description,
                type=node.type.value,
                parent_id=node.parent_id,
                children=node.children,
                enabled=node.enabled,
            )
            for node in workflow.tree
        ]

    @app.delete("/api/workflows/{workflow_id}/agents/{agent_id}")
    async def remove_agent(workflow_id: str, agent_id: str):
        """Remove an agent from a workflow."""
        manager = get_workflow_manager()
        workflow = await manager.get_workflow(workflow_id)

        if not workflow:
            raise HTTPException(status_code=404, detail="Workflow not found")

        removed = workflow.remove_agent(agent_id)
        if not removed:
            raise HTTPException(status_code=404, detail="Agent not found")

        # Clean up agent bindings in global managers to prevent memory leaks and orphaned data
        try:
            # Unbind Skills
            from ..plugins.skill_manager import get_skill_manager
            skill_manager = get_skill_manager()
            for skill in skill_manager.get_skills_for_agent(agent_id):
                await skill_manager.unbind_skill_from_agent(skill.id, agent_id)
                
            # Unbind MCP Servers
            from ..plugins.mcp_manager import get_mcp_manager
            mcp_manager = get_mcp_manager()
            for mcp in mcp_manager.get_servers_for_agent(agent_id):
                mcp_manager.unbind_server_from_agent(mcp.id, agent_id)
        except Exception as e:
            # We don't want to fail the agent deletion if binding cleanup fails
            print(f"Warning: Failed to clean up bindings for deleted agent {agent_id}: {e}")

        # Persist changes
        await manager.save_current_state(workflow_id)

        return {"status": "removed", "id": agent_id}

    # ============== Workflow Nesting Endpoints ==============

    @app.post(
        "/api/workflows/{workflow_id}/agents/{agent_id}/bind-workflow",
        summary="将 Agent 节点绑定为子工作流（实现无限嵌套树）",
    )
    async def bind_agent_to_workflow(
        workflow_id: str,
        agent_id: str,
        body: Dict[str, Any],
    ):
        """
        将一个 Agent 节点转换为 WORKFLOW 类型，使其代理调用另一个完整工作流。

        这实现了无限深度的树形嵌套结构：
          Portal → WorkflowA → AgentX (type=WORKFLOW) → WorkflowB → AgentY → WorkflowC → ...

        body 参数：
        - sub_workflow_id (str, required): 要绑定的子工作流 ID
        - input_mapping (dict, optional): 输入键映射 {"target_key": "source_key"}
        - output_mapping (dict, optional): 输出键映射 {"target_key": "source_key"}

        绑定后该 Agent 节点在执行时会：
        1. 透明地调用整个子工作流（含其所有 agents）
        2. 将子工作流的最终输出返回给父工作流继续处理
        3. 自动检测循环引用，防止无限递归
        """
        from ..core.models import AgentType, AgentConfig, WorkflowReferenceConfig

        manager = get_workflow_manager()
        workflow = await manager.get_workflow(workflow_id)
        if not workflow:
            raise HTTPException(status_code=404, detail="Workflow not found")

        node = workflow.get_agent(agent_id)
        if not node:
            raise HTTPException(status_code=404, detail="Agent not found")

        sub_workflow_id = body.get("sub_workflow_id")
        if not sub_workflow_id:
            raise HTTPException(status_code=400, detail="sub_workflow_id is required")

        # 防止自引用
        if sub_workflow_id == workflow_id:
            raise HTTPException(
                status_code=400,
                detail="A workflow cannot reference itself (direct self-loop)",
            )

        # 验证子工作流存在
        sub_workflow = await manager.get_workflow(sub_workflow_id)
        if not sub_workflow:
            raise HTTPException(
                status_code=404,
                detail=f"Sub-workflow '{sub_workflow_id}' not found",
            )

        # 更新 Agent 节点类型和配置
        node.type = AgentType.WORKFLOW
        if node.config is None:
            node.config = AgentConfig()

        node.config.workflow_config = WorkflowReferenceConfig(
            workflow_id=sub_workflow_id,
            input_mapping=body.get("input_mapping", {}),
            output_mapping=body.get("output_mapping", {}),
        )

        # 清除 builtin_definition（不再作为独立 LLM agent）
        node.config.builtin_definition = None

        # 重置 executor 使其在下次运行时重新初始化（带新的适配器）
        workflow.executor = None
        workflow.state = WorkflowState.CREATED

        await manager.save_current_state(workflow_id)

        return {
            "status": "bound",
            "agent_id": agent_id,
            "agent_name": node.name,
            "sub_workflow_id": sub_workflow_id,
            "sub_workflow_name": sub_workflow.name,
            "input_mapping": body.get("input_mapping", {}),
            "output_mapping": body.get("output_mapping", {}),
        }

    @app.delete(
        "/api/workflows/{workflow_id}/agents/{agent_id}/bind-workflow",
        summary="解除 Agent 节点的子工作流绑定",
    )
    async def unbind_agent_from_workflow(workflow_id: str, agent_id: str):
        """
        将一个 WORKFLOW 类型的 Agent 节点还原为普通 BUILTIN 节点。
        解绑后该节点保留其名称和描述，但不再委托给子工作流。
        """
        from ..core.models import AgentType

        manager = get_workflow_manager()
        workflow = await manager.get_workflow(workflow_id)
        if not workflow:
            raise HTTPException(status_code=404, detail="Workflow not found")

        node = workflow.get_agent(agent_id)
        if not node:
            raise HTTPException(status_code=404, detail="Agent not found")

        if node.type != AgentType.WORKFLOW:
            raise HTTPException(
                status_code=400,
                detail="Agent is not of WORKFLOW type (not bound to a sub-workflow)",
            )

        prev_sub_id = (
            node.config.workflow_config.workflow_id
            if node.config and node.config.workflow_config
            else None
        )

        # 还原为 builtin，清除 workflow_config
        node.type = AgentType.BUILTIN
        if node.config:
            node.config.workflow_config = None

        workflow.executor = None
        workflow.state = WorkflowState.CREATED

        await manager.save_current_state(workflow_id)

        return {
            "status": "unbound",
            "agent_id": agent_id,
            "agent_name": node.name,
            "previous_sub_workflow_id": prev_sub_id,
        }

    @app.get(
        "/api/workflows/{workflow_id}/agents/{agent_id}/bind-workflow",
        summary="查看 Agent 节点当前绑定的子工作流",
    )
    async def get_agent_workflow_binding(workflow_id: str, agent_id: str):
        """获取一个 Agent 节点当前绑定的子工作流信息。"""
        from ..core.models import AgentType

        manager = get_workflow_manager()
        workflow = await manager.get_workflow(workflow_id)
        if not workflow:
            raise HTTPException(status_code=404, detail="Workflow not found")

        node = workflow.get_agent(agent_id)
        if not node:
            raise HTTPException(status_code=404, detail="Agent not found")

        if node.type != AgentType.WORKFLOW or not (
            node.config and node.config.workflow_config
        ):
            return {"bound": False, "agent_id": agent_id, "type": node.type.value}

        wf_cfg = node.config.workflow_config
        sub_wf = await manager.get_workflow(wf_cfg.workflow_id)

        return {
            "bound": True,
            "agent_id": agent_id,
            "agent_name": node.name,
            "sub_workflow_id": wf_cfg.workflow_id,
            "sub_workflow_name": sub_wf.name if sub_wf else None,
            "sub_workflow_description": sub_wf.description if sub_wf else None,
            "input_mapping": wf_cfg.input_mapping,
            "output_mapping": wf_cfg.output_mapping,
        }

    @app.get(
        "/api/workflows/{workflow_id}/tree",
        summary="获取工作流完整嵌套树结构（递归展开所有子工作流）",
    )
    async def get_workflow_full_tree(workflow_id: str, max_depth: int = 5):
        """
        递归展开工作流的完整嵌套树结构，包含所有子工作流节点。

        每个 WORKFLOW 类型的 Agent 节点都会附带 sub_workflow 字段，
        其中包含子工作流的完整结构（继续递归）。

        参数：
        - max_depth: 最大递归深度，默认 5，防止超深结构导致响应过慢

        返回示例：
        {
          "id": "wf-A", "name": "旅游助手",
          "agents": [
            {"id": "...", "name": "行程规划", "type": "builtin"},
            {
              "id": "...", "name": "酒店预订", "type": "workflow",
              "sub_workflow_id": "wf-B",
              "sub_workflow": {
                "id": "wf-B", "name": "酒店工作流",
                "agents": [ ... ]
              }
            }
          ]
        }
        """
        manager = get_workflow_manager()

        async def build_tree(wf_id: str, depth: int, visited: set) -> Dict[str, Any]:
            if wf_id in visited:
                return {
                    "id": wf_id,
                    "truncated": True,
                    "reason": "circular_reference",
                }
            if depth > max_depth:
                return {
                    "id": wf_id,
                    "truncated": True,
                    "reason": f"max_depth ({max_depth}) exceeded",
                }

            visited = visited | {wf_id}
            wf = await manager.get_workflow(wf_id)
            if not wf:
                return {"id": wf_id, "error": "workflow not found"}

            agents = []
            for node in wf.tree:
                agent_info: Dict[str, Any] = {
                    "id": node.id,
                    "name": node.name,
                    "description": node.description,
                    "type": node.type.value,
                    "parent_id": node.parent_id,
                    "children": node.children,
                    "routing_strategy": node.routing_strategy.value,
                    "enabled": node.enabled,
                }
                # WORKFLOW 节点递归展开
                from ..core.models import AgentType
                if (
                    node.type == AgentType.WORKFLOW
                    and node.config
                    and node.config.workflow_config
                    and node.config.workflow_config.workflow_id
                ):
                    sub_id = node.config.workflow_config.workflow_id
                    agent_info["sub_workflow_id"] = sub_id
                    agent_info["input_mapping"] = node.config.workflow_config.input_mapping
                    agent_info["output_mapping"] = node.config.workflow_config.output_mapping
                    agent_info["sub_workflow"] = await build_tree(
                        sub_id, depth + 1, visited
                    )
                agents.append(agent_info)

            return {
                "id": wf.id,
                "name": wf.name,
                "description": wf.description,
                "state": wf.state.value,
                "agent_count": len(agents),
                "agents": agents,
            }

        return await build_tree(workflow_id, depth=0, visited=set())

    # ============== Plugin Endpoints ==============

    @app.post("/api/plugins/mcp")
    async def register_mcp(request: RegisterMCPRequest):
        """Register an MCP server."""
        config = MCPServerConfig(
            name=request.name,
            command=request.command,
            args=request.args,
            env=request.env,
        )

        if request.is_global:
            from ..plugins.mcp_manager import get_mcp_manager
            manager = get_mcp_manager()
            server = manager.register_server(
                config=config,
                description=f"Globally installed MCP Server: {request.name}"
            )
            
            # If agent_id provided, bind it immediately
            if request.agent_id:
                manager.bind_server_to_agent(server.id, request.agent_id)
                # Also register dynamically in registry so it's immediately available to the agent
                registry = get_plugin_registry()
                await registry.register_mcp(config, request.agent_id)
                
            return {
                "status": "registered_globally",
                "server_id": server.id,
                "name": request.name,
            }
        else:
            registry = get_plugin_registry()
            plugin = await registry.register_mcp(config, request.agent_id)
            return {
                "status": "registered",
                "name": request.name,
                "tools": [t.name for t in plugin.get_tools()],
            }

    @app.post("/api/plugins/skill")
    async def register_skill(request: RegisterSkillRequest):
        """Register a skill."""
        registry = get_plugin_registry()

        config = SkillConfig(
            name=request.name,
            description=request.description,
            module_path=request.module_path,
            function_name=request.function_name,
        )

        plugin = await registry.register_skill(config, request.agent_id)

        return {
            "status": "registered",
            "name": request.name,
            "tools": [t.name for t in plugin.get_tools()],
        }

    @app.post("/api/plugins/rag")
    async def register_rag(request: RegisterRAGRequest):
        """Register a RAG source."""
        registry = get_plugin_registry()

        config = RAGSourceConfig(
            name=request.name,
            type=request.type,
            connection_string=request.connection_string,
            collection_name=request.collection_name,
        )

        plugin = await registry.register_rag(config, request.agent_id)

        return {
            "status": "registered",
            "name": request.name,
            "tools": [t.name for t in plugin.get_tools()],
        }

    @app.get("/api/plugins")
    async def list_plugins():
        """List all registered plugins."""
        registry = get_plugin_registry()
        plugins = registry.get_all_plugins()

        return [
            {
                "id": plugin_id,
                "type": plugin.plugin_type,
                "enabled": plugin.is_enabled,
                "tools": [t.name for t in plugin.get_tools()],
            }
            for plugin_id, plugin in plugins.items()
        ]

    @app.delete("/api/plugins/{plugin_id}")
    async def remove_plugin(plugin_id: str):
        """Remove a plugin."""
        registry = get_plugin_registry()
        plugin = await registry.remove_plugin(plugin_id)

        if not plugin:
            raise HTTPException(status_code=404, detail="Plugin not found")

        return {"status": "removed", "id": plugin_id}

    @app.get("/api/mcp")
    async def list_mcps():
        """List all globally installed MCP servers."""
        from ..plugins.mcp_manager import get_mcp_manager
        manager = get_mcp_manager()
        servers = manager.list_servers()
        
        return [
            {
                "id": server.id,
                "name": server.config.name,
                "description": server.description,
                "version": server.version,
                "author": server.author,
                "tags": server.tags,
                "enabled": server.enabled,
                "installed_at": server.installed_at.isoformat(),
                "agent_count": len(server.agent_ids),
                "command": server.config.command,
                "args": server.config.args,
                "env": server.config.env,
            }
            for server in servers
        ]

    @app.delete("/api/mcp/{server_id}")
    async def unregister_mcp(server_id: str):
        """Unregister a globally installed MCP server."""
        from ..plugins.mcp_manager import get_mcp_manager
        success = get_mcp_manager().unregister_server(server_id)
        if not success:
            raise HTTPException(status_code=404, detail="MCP server not found")
        return {"status": "success"}

    @app.post("/api/mcp/{server_id}/bind/{agent_id}")
    async def bind_mcp_to_agent(server_id: str, agent_id: str):
        """Bind a global MCP server to an agent."""
        from ..plugins.mcp_manager import get_mcp_manager
        success = get_mcp_manager().bind_server_to_agent(server_id, agent_id)
        if not success:
            raise HTTPException(status_code=404, detail="MCP server not found")
        return {"status": "success"}

    @app.post("/api/mcp/{server_id}/unbind/{agent_id}")
    async def unbind_mcp_from_agent(server_id: str, agent_id: str):
        """Unbind a global MCP server from an agent."""
        from ..plugins.mcp_manager import get_mcp_manager
        success = get_mcp_manager().unbind_server_from_agent(server_id, agent_id)
        if not success:
            raise HTTPException(status_code=404, detail="MCP server not found")
        return {"status": "success"}

    # ============== Skill Management Endpoints ==============

    @app.post("/api/skills/upload")
    async def upload_skill(file: UploadFile = File(...)):
        """Upload and install a skill package (.zip or .skill file)."""
        import tempfile
        import os
        from pathlib import Path

        # Save uploaded file to temporary location
        upload_filename = file.filename or "upload.skill"
        with tempfile.NamedTemporaryFile(delete=False, suffix=Path(str(upload_filename)).suffix) as temp_file:
            content = await file.read()
            temp_file.write(content)
            temp_file_path = temp_file.name

        try:
            # Install the skill
            skill_manager = get_skill_manager()
            try:
                installed_skill = await skill_manager.install_skill(temp_file_path)
            except (ValueError, FileNotFoundError) as e:
                raise HTTPException(status_code=400, detail=str(e))

            # Register the skill as a plugin
            plugin_registry = get_plugin_registry()
            skill_config = skill_manager.get_skill_config(installed_skill.id)
            if skill_config:
                await plugin_registry.register_skill(skill_config)

            return {
                "status": "installed",
                "skill_id": installed_skill.id,
                "name": installed_skill.metadata.name,
                "description": installed_skill.metadata.description,
            }
        finally:
            # Clean up temporary file
            if os.path.exists(temp_file_path):
                os.unlink(temp_file_path)

    @app.get("/api/skills")
    async def list_skills():
        """List all installed skills."""
        skill_manager = get_skill_manager()
        skills = skill_manager.list_skills()

        return [
            {
                "id": skill.id,
                "name": skill.metadata.name,
                "description": skill.metadata.description,
                "version": skill.metadata.version,
                "author": skill.metadata.author,
                "tags": skill.metadata.tags,
                "enabled": skill.enabled,
                "installed_at": skill.installed_at.isoformat(),
                "agent_count": len(skill.agent_ids),
                "readme": skill.metadata.readme,
                "parameters_schema": skill.metadata.parameters_schema,
                "dependencies": skill.metadata.dependencies,
            }
            for skill in skills
        ]

    @app.post("/api/skills/{skill_id}/bind/{agent_id}")
    async def bind_skill_to_agent(skill_id: str, agent_id: str):
        """Bind a skill to an agent."""
        skill_manager = get_skill_manager()
        success = await skill_manager.bind_skill_to_agent(skill_id, agent_id)

        if not success:
            raise HTTPException(status_code=404, detail="Skill not found")

        return {"status": "bound", "skill_id": skill_id, "agent_id": agent_id}

    @app.post("/api/skills/{skill_id}/unbind/{agent_id}")
    async def unbind_skill_from_agent(skill_id: str, agent_id: str):
        """Unbind a skill from an agent."""
        skill_manager = get_skill_manager()
        success = await skill_manager.unbind_skill_from_agent(skill_id, agent_id)

        if not success:
            raise HTTPException(status_code=404, detail="Skill not found")

        return {"status": "unbound", "skill_id": skill_id, "agent_id": agent_id}

    @app.get("/api/agents/{agent_id}/mcp")
    async def get_agent_mcps(agent_id: str):
        """Get all MCP servers bound to an agent."""
        from ..plugins.mcp_manager import get_mcp_manager
        manager = get_mcp_manager()
        servers = manager.get_servers_for_agent(agent_id)
        
        return [
            {
                "id": server.id,
                "name": server.config.name,
                "description": server.description,
                "version": server.version,
                "author": server.author,
                "tags": server.tags,
                "enabled": server.enabled,
                "installed_at": server.installed_at.isoformat(),
                "agent_count": len(server.agent_ids),
                "command": server.config.command,
                "args": server.config.args,
                "env": server.config.env,
            }
            for server in servers
        ]

    @app.get("/api/agents/{agent_id}/skills")
    async def get_agent_skills(agent_id: str):
        """Get all skills bound to an agent."""
        skill_manager = get_skill_manager()
        skills = skill_manager.get_skills_for_agent(agent_id)

        return [
            {
                "id": skill.id,
                "name": skill.metadata.name,
                "description": skill.metadata.description,
                "version": skill.metadata.version,
                "author": skill.metadata.author,
                "tags": skill.metadata.tags,
                "enabled": skill.enabled,
                "installed_at": skill.installed_at.isoformat(),
            }
            for skill in skills
        ]

    @app.delete("/api/skills/{skill_id}")
    async def uninstall_skill(skill_id: str):
        """Uninstall a skill."""
        skill_manager = get_skill_manager()
        success = await skill_manager.uninstall_skill(skill_id)

        if not success:
            raise HTTPException(status_code=404, detail="Skill not found")

        return {"status": "uninstalled", "skill_id": skill_id}

    # ============== System Tools Endpoints ==============

    @app.get("/api/system-tools")
    async def list_system_tools():
        """List all available system tools."""
        from ..tools.registry import get_system_tool_registry
        registry = get_system_tool_registry()

        tools = registry.to_list()
        return {
            "tools": tools,
            "categories": registry.get_categories(),
        }

    @app.get("/api/system-tools/categories")
    async def list_system_tool_categories():
        """List all system tool categories."""
        from ..tools.registry import get_system_tool_registry
        registry = get_system_tool_registry()

        categories = registry.get_categories()
        tools_by_category = {}
        for cat in categories:
            tools_by_category[cat] = [t.to_dict() for t in registry.list_by_category(cat)]

        return {
            "categories": categories,
            "tools_by_category": tools_by_category,
        }

    @app.get("/api/system-tools/{tool_name}")
    async def get_system_tool(tool_name: str):
        """Get details of a specific system tool."""
        from ..tools.registry import get_system_tool_registry
        registry = get_system_tool_registry()

        tool = registry.get(tool_name)
        if not tool:
            raise HTTPException(status_code=404, detail="System tool not found")

        return tool.to_dict()

    # ============== Built-in Agent Editor Endpoints ==============

    @app.get("/api/workflows/{workflow_id}/agents/{agent_id}/definition")
    async def get_agent_definition(workflow_id: str, agent_id: str):
        """Get the full definition of a built-in agent for editing."""
        manager = get_workflow_manager()
        workflow = await manager.get_workflow(workflow_id)

        if not workflow:
            raise HTTPException(status_code=404, detail="Workflow not found")

        node = workflow.get_agent(agent_id)
        if not node:
            raise HTTPException(status_code=404, detail="Agent not found")

        # Return the full configuration
        return {
            "id": node.id,
            "name": node.name,
            "description": node.description,
            "type": node.type.value,
            "config": node.config.model_dump() if node.config else {},
            "routing_strategy": node.routing_strategy.value,
            "routing_conditions": node.routing_conditions,
            "max_depth": node.max_depth,
            "timeout": node.timeout,
            "enabled": node.enabled,
            "builtin_definition": node.config.builtin_definition.model_dump() if node.config and node.config.builtin_definition else None,
        }

    @app.put("/api/workflows/{workflow_id}/agents/{agent_id}/definition")
    async def update_agent_definition(workflow_id: str, agent_id: str, definition: Dict[str, Any]):
        """Update the full definition of a built-in agent."""
        manager = get_workflow_manager()
        workflow = await manager.get_workflow(workflow_id)

        if not workflow:
            raise HTTPException(status_code=404, detail="Workflow not found")

        node = workflow.get_agent(agent_id)
        if not node:
            raise HTTPException(status_code=404, detail="Agent not found")

        # Update basic fields
        if "name" in definition:
            node.name = definition["name"]
        if "description" in definition:
            node.description = definition["description"]
        if "routing_strategy" in definition:
            node.routing_strategy = RoutingStrategy(definition["routing_strategy"])
        if "routing_conditions" in definition:
            node.routing_conditions = definition["routing_conditions"]
        if "max_depth" in definition:
            node.max_depth = definition["max_depth"]
        if "timeout" in definition:
            node.timeout = definition["timeout"]
        if "enabled" in definition:
            node.enabled = definition["enabled"]

        # Update builtin definition
        if "builtin_definition" in definition and definition["builtin_definition"]:
            node.type = AgentType.BUILTIN
            if node.config is None:
                node.config = AgentConfig()
            node.config.builtin_definition = BuiltinAgentDefinition(**definition["builtin_definition"])

        # Persist changes
        await manager.save_current_state(workflow_id)

        return {"status": "updated", "id": agent_id}

    @app.post("/api/workflows/{workflow_id}/agents/{agent_id}/tools")
    async def add_agent_tool(workflow_id: str, agent_id: str, tool: Dict[str, Any]):
        """Add a built-in tool to an agent."""
        manager = get_workflow_manager()
        workflow = await manager.get_workflow(workflow_id)

        if not workflow:
            raise HTTPException(status_code=404, detail="Workflow not found")

        node = workflow.get_agent(agent_id)
        if not node:
            raise HTTPException(status_code=404, detail="Agent not found")

        # Ensure builtin definition exists
        if node.config is None:
            node.config = AgentConfig()
        if node.config.builtin_definition is None:
            node.config.builtin_definition = BuiltinAgentDefinition(name=node.name)
            node.type = AgentType.BUILTIN

        # Convert parameters
        parameters = []
        for param in tool.get("parameters", []):
            parameters.append(ToolParameter(
                name=param["name"],
                type=ToolParameterType(param.get("type", "string")),
                description=param.get("description", ""),
                required=param.get("required", True),
                default=param.get("default"),
                enum=param.get("enum"),
            ))

        # Create tool definition
        tool_def = BuiltinToolDefinition(
            name=tool["name"],
            description=tool.get("description", ""),
            tool_type=tool.get("tool_type", "http"),
            parameters=parameters,
            http_method=tool.get("http_method", "GET"),
            http_url=tool.get("http_url", ""),
            http_headers=tool.get("http_headers", {}),
            http_body_template=tool.get("http_body_template"),
            code=tool.get("code"),
            timeout=tool.get("timeout", 30.0),
            approval_required=tool.get("approval_required", False),
        )

        node.config.builtin_definition.builtin_tools.append(tool_def)

        # Persist changes
        await manager.save_current_state(workflow_id)

        return {"status": "added", "tool_name": tool["name"]}

    @app.delete("/api/workflows/{workflow_id}/agents/{agent_id}/tools/{tool_name}")
    async def remove_agent_tool(workflow_id: str, agent_id: str, tool_name: str):
        """Remove a built-in tool from an agent."""
        manager = get_workflow_manager()
        workflow = await manager.get_workflow(workflow_id)

        if not workflow:
            raise HTTPException(status_code=404, detail="Workflow not found")

        node = workflow.get_agent(agent_id)
        if not node:
            raise HTTPException(status_code=404, detail="Agent not found")

        if not node.config or not node.config.builtin_definition:
            raise HTTPException(status_code=400, detail="Agent has no builtin definition")

        # Remove tool by name
        original_count = len(node.config.builtin_definition.builtin_tools)
        node.config.builtin_definition.builtin_tools = [
            t for t in node.config.builtin_definition.builtin_tools
            if t.name != tool_name
        ]

        if len(node.config.builtin_definition.builtin_tools) == original_count:
            raise HTTPException(status_code=404, detail="Tool not found")

        # Persist changes
        await manager.save_current_state(workflow_id)

        return {"status": "removed", "tool_name": tool_name}

    @app.post("/api/workflows/{workflow_id}/agents/{agent_id}/test")
    async def test_agent(workflow_id: str, agent_id: str, request: Dict[str, Any]):
        """Test an agent with a sample message."""
        manager = get_workflow_manager()
        workflow = await manager.get_workflow(workflow_id)

        if not workflow:
            raise HTTPException(status_code=404, detail="Workflow not found")

        node = workflow.get_agent(agent_id)
        if not node:
            raise HTTPException(status_code=404, detail="Agent not found")

        message = request.get("message", "Hello, this is a test.")

        # Initialize workflow if needed
        if workflow.state.value == "created":
            await workflow.initialize()

        # Run just this agent
        from ..core.context import ExecutionContext
        from ..core.models import ChatMessage, MessageRole
        from ..adapters.base import AdapterFactory

        try:
            adapter = await AdapterFactory.create_async(node)
            ctx = ExecutionContext()
            messages = [ChatMessage(role=MessageRole.USER, content=message)]

            response = await adapter.run(messages, ctx)

            return {
                "status": "success",
                "response": {
                    "messages": [m.model_dump() for m in response.messages],
                    "tool_calls": [t.model_dump() for t in response.tool_calls],
                },
            }
        except Exception as e:
            return {
                "status": "error",
                "error": str(e),
            }

    # ============== Agent Templates ==============

    # In-memory cache for templates (loaded from storage)
    _agent_templates: Dict[str, AgentTemplate] = {}
    _templates_loaded = False

    async def _ensure_templates_loaded():
        """Load templates from storage if not already loaded."""
        nonlocal _templates_loaded
        if _templates_loaded:
            return

        try:
            from ..storage import get_storage_manager
            storage = get_storage_manager()
            template_dicts = await storage.list_templates()

            for tpl_dict in template_dicts:
                try:
                    definition = BuiltinAgentDefinition(**tpl_dict.get("definition", {}))
                    agent_template = AgentTemplate(
                        id=tpl_dict["id"],
                        name=tpl_dict["name"],
                        description=tpl_dict.get("description", ""),
                        category=tpl_dict.get("category", "custom"),
                        icon=tpl_dict.get("icon", ""),
                        definition=definition,
                        is_official=tpl_dict.get("is_official", False),
                        author=tpl_dict.get("author", "user"),
                    )
                    _agent_templates[agent_template.id] = agent_template
                except Exception as e:
                    logger.error(f"Error loading template: {e}")

            _templates_loaded = True
            logger.info(f"Loaded {len(_agent_templates)} custom templates from storage")
        except Exception as e:
            logger.error(f"Error loading templates: {e}")
            _templates_loaded = True  # Don't retry on error

    @app.get("/api/templates")
    async def list_templates():
        """List all available agent templates."""
        await _ensure_templates_loaded()

        # Return built-in templates + custom templates
        templates = list(_agent_templates.values())

        # Add built-in templates
        builtin_templates = _get_builtin_templates()
        templates.extend(builtin_templates)

        return [
            {
                "id": t.id,
                "name": t.name,
                "description": t.description,
                "category": t.category,
                "icon": t.icon,
                "is_official": t.is_official,
            }
            for t in templates
        ]

    @app.get("/api/templates/{template_id}")
    async def get_template(template_id: str):
        """Get a template by ID."""
        await _ensure_templates_loaded()

        # Check custom templates first
        if template_id in _agent_templates:
            return _agent_templates[template_id].model_dump()

        # Check built-in templates
        for t in _get_builtin_templates():
            if t.id == template_id:
                return t.model_dump()

        raise HTTPException(status_code=404, detail="Template not found")

    @app.post("/api/templates")
    async def create_template(template: Dict[str, Any]):
        """Create a new agent template."""
        await _ensure_templates_loaded()

        template_id = template.get("id") or str(uuid4())

        definition = BuiltinAgentDefinition(**template.get("definition", {}))

        agent_template = AgentTemplate(
            id=template_id,
            name=template["name"],
            description=template.get("description", ""),
            category=template.get("category", "custom"),
            icon=template.get("icon", ""),
            definition=definition,
            is_official=False,
            author=template.get("author", "user"),
        )

        _agent_templates[template_id] = agent_template

        # Persist to storage
        try:
            from ..storage import get_storage_manager
            storage = get_storage_manager()
            await storage.save_template(agent_template.model_dump())
        except Exception as e:
            logger.error(f"Error saving template: {e}")

        return {"status": "created", "id": template_id}

    @app.delete("/api/templates/{template_id}")
    async def delete_template(template_id: str):
        """Delete a custom template."""
        await _ensure_templates_loaded()

        # Can't delete built-in templates
        for t in _get_builtin_templates():
            if t.id == template_id:
                raise HTTPException(status_code=400, detail="Cannot delete built-in template")

        if template_id not in _agent_templates:
            raise HTTPException(status_code=404, detail="Template not found")

        del _agent_templates[template_id]

        # Delete from storage
        try:
            from ..storage import get_storage_manager
            storage = get_storage_manager()
            await storage.delete_template(template_id)
        except Exception as e:
            logger.error(f"Error deleting template: {e}")

        return {"status": "deleted", "id": template_id}

    @app.post("/api/workflows/{workflow_id}/agents/from-template")
    async def create_agent_from_template(workflow_id: str, request: Dict[str, Any]):
        """Create a new agent from a template."""
        manager = get_workflow_manager()
        workflow = await manager.get_workflow(workflow_id)

        if not workflow:
            raise HTTPException(status_code=404, detail="Workflow not found")

        template_id = request.get("template_id")
        if not template_id:
            raise HTTPException(status_code=400, detail="template_id is required")

        # Find template
        template = None
        if template_id in _agent_templates:
            template = _agent_templates[template_id]
        else:
            for t in _get_builtin_templates():
                if t.id == template_id:
                    template = t
                    break

        if not template:
            raise HTTPException(status_code=404, detail="Template not found")

        # Create agent from template
        name = request.get("name") or template.definition.name
        parent_id = request.get("parent_id")

        node = AgentNode(
            name=name,
            description=template.definition.description,
            type=AgentType.BUILTIN,
            config=AgentConfig(
                model=template.definition.model,
                temperature=template.definition.temperature,
                max_tokens=template.definition.max_tokens,
                builtin_definition=template.definition.model_copy(deep=True),
            ),
            parent_id=parent_id,
        )

        workflow.add_agent(node, parent_id)

        # Persist changes
        await manager.save_current_state(workflow_id)

        return {
            "status": "created",
            "id": node.id,
            "name": node.name,
        }

    # ============== Workflow Template Endpoints ==============

    @app.get("/api/workflow-templates")
    async def list_workflow_templates():
        """列出所有可用的工作流模板"""
        templates = _get_builtin_workflow_templates()
        return [
            {
                "id": t.id,
                "name": t.name,
                "description": t.description,
                "category": t.category,
                "icon": t.icon,
                "is_official": t.is_official,
                "agent_count": len(t.agents),
            }
            for t in templates
        ]

    @app.get("/api/workflow-templates/{template_id}")
    async def get_workflow_template(template_id: str):
        """获取工作流模板详情"""
        for t in _get_builtin_workflow_templates():
            if t.id == template_id:
                # 丰富 agent 信息
                agent_details = []
                for agent_ref in t.agents:
                    agent_tpl = None
                    for at in _get_builtin_templates():
                        if at.id == agent_ref.template_id:
                            agent_tpl = at
                            break
                    agent_details.append({
                        "ref_id": agent_ref.ref_id,
                        "template_id": agent_ref.template_id,
                        "name": agent_ref.name_override or (agent_tpl.name if agent_tpl else "Unknown"),
                        "description": agent_tpl.description if agent_tpl else "",
                        "parent_ref": agent_ref.parent_ref,
                        "icon": agent_tpl.icon if agent_tpl else "",
                    })
                return {
                    "id": t.id,
                    "name": t.name,
                    "description": t.description,
                    "category": t.category,
                    "icon": t.icon,
                    "is_official": t.is_official,
                    "agents": agent_details,
                }

        raise HTTPException(status_code=404, detail="Workflow template not found")

    @app.post("/api/workflow-templates/{template_id}/create")
    async def create_workflow_from_template(template_id: str, request: Dict[str, Any] = {}):
        """从工作流模板一键创建完整工作流"""
        # 查找工作流模板
        wf_template = None
        for t in _get_builtin_workflow_templates():
            if t.id == template_id:
                wf_template = t
                break

        if not wf_template:
            raise HTTPException(status_code=404, detail="Workflow template not found")

        # 构建 Agent 模板索引
        agent_tpl_index: Dict[str, AgentTemplate] = {}
        for at in _get_builtin_templates():
            agent_tpl_index[at.id] = at

        # 创建工作流
        wf_name = request.get("name", wf_template.name)
        wf_desc = request.get("description", wf_template.description)

        manager = get_workflow_manager()
        workflow = await manager.create_workflow(name=wf_name, description=wf_desc)

        # 追踪 ref_id -> 实际 agent_id 的映射
        ref_to_id: Dict[str, str] = {}

        # 按依赖顺序创建 Agent（先创建没有 parent 的，再创建有 parent 的）
        pending = list(wf_template.agents)
        max_iterations = len(pending) * 2  # 防止死循环
        iteration = 0

        while pending and iteration < max_iterations:
            iteration += 1
            next_pending = []

            for agent_ref in pending:
                # 如果有 parent_ref，需要先等 parent 创建完成
                if agent_ref.parent_ref and agent_ref.parent_ref not in ref_to_id:
                    next_pending.append(agent_ref)
                    continue

                # 查找对应的 Agent 模板
                agent_tpl = agent_tpl_index.get(agent_ref.template_id)
                if not agent_tpl:
                    logger.error(f"Agent template not found: {agent_ref.template_id}")
                    continue

                # 确定父节点的实际 ID
                parent_id = ref_to_id.get(agent_ref.parent_ref) if agent_ref.parent_ref else None

                # 创建 Agent
                node = AgentNode(
                    name=agent_ref.name_override or agent_tpl.definition.name,
                    description=agent_tpl.definition.description,
                    type=AgentType.BUILTIN,
                    config=AgentConfig(
                        model=agent_tpl.definition.model,
                        temperature=agent_tpl.definition.temperature,
                        max_tokens=agent_tpl.definition.max_tokens,
                        builtin_definition=agent_tpl.definition.model_copy(deep=True),
                    ),
                    # Root agents use COORDINATOR pattern (run → specialists → integrate)
                    # Child agents use SEQUENTIAL (simple pass-through)
                    routing_strategy=RoutingStrategy.COORDINATOR if not agent_ref.parent_ref else RoutingStrategy.SEQUENTIAL,
                    parent_id=parent_id,
                )

                workflow.add_agent(node, parent_id)
                ref_to_id[agent_ref.ref_id] = node.id

            pending = next_pending

        # 持久化
        await manager.save_current_state(workflow.id)

        return {
            "status": "created",
            "workflow_id": workflow.id,
            "name": workflow.name,
            "agent_count": len(workflow.tree),
            "agents": [
                {"ref_id": ref_id, "agent_id": agent_id}
                for ref_id, agent_id in ref_to_id.items()
            ],
        }

    # ============== Copilot Endpoints ==============

    @app.post("/api/copilot/sessions")
    async def create_copilot_session(request: Optional[Dict[str, Any]] = None):
        """Create a new copilot session, optionally associated with a workflow."""
        from ..copilot import get_copilot_service
        copilot = get_copilot_service()

        # Extract workflow_id from request if provided
        workflow_id = None
        if request:
            workflow_id = request.get("workflow_id")

        session = await copilot.create_session()

        # Set workflow_id if provided (for editing existing workflows)
        if workflow_id:
            session.workflow_id = workflow_id

        return {"session_id": session.session_id}

    @app.get("/api/copilot/config")
    async def get_copilot_config():
        """Get current Copilot configuration."""
        from ..copilot import get_copilot_service
        copilot = get_copilot_service()
        return copilot.get_config()

    @app.post("/api/copilot/config")
    async def update_copilot_config(request: CopilotConfigRequest):
        """
        Update Copilot configuration at runtime.

        Allows configuring:
        - provider: The LLM provider (openai, zhipu, deepseek, qwen, anthropic, moonshot, yi, baichuan, ollama)
        - model: The LLM model to use (e.g., gpt-4, glm-4, deepseek-chat)
        - api_key: API key for the LLM provider
        - base_url: Base URL for custom/local providers (e.g., http://localhost:11434/v1 for Ollama)
        """
        from ..copilot import get_copilot_service
        copilot = get_copilot_service()
        await copilot.update_config(
            provider=request.provider,
            model=request.model,
            api_key=request.api_key,
            base_url=request.base_url,
        )
        return {
            "status": "updated",
            "config": copilot.get_config(),
        }

    @app.get("/api/copilot/sessions/{session_id}")
    async def get_copilot_session(session_id: str):
        """Get session with conversation history."""
        from ..copilot import get_copilot_service
        copilot = get_copilot_service()
        session = await copilot.get_session(session_id)

        if not session:
            raise HTTPException(status_code=404, detail="Session not found")

        return {
            "session_id": session.session_id,
            "workflow_id": session.workflow_id,
            "messages": [
                {
                    "role": m.role,
                    "content": m.content,
                    "timestamp": m.timestamp.isoformat(),
                }
                for m in session.messages
            ],
            "created_at": session.created_at.isoformat(),
            "updated_at": session.updated_at.isoformat(),
        }

    @app.post("/api/copilot/chat")
    async def copilot_chat(request: CopilotChatRequest):
        """Chat with copilot to generate/modify workflow."""
        from ..copilot import get_copilot_service
        copilot = get_copilot_service()

        if request.stream:
            async def generate():
                async for event in copilot.chat(
                    request.session_id,
                    request.message,
                    stream=True
                ):
                    event_data = event.model_dump(exclude_none=True)
                    # Convert datetime to string
                    if "timestamp" in event_data:
                        event_data["timestamp"] = event_data["timestamp"].isoformat()
                    yield f"data: {json.dumps(event_data, ensure_ascii=False)}\n\n"
                yield "data: [DONE]\n\n"

            return StreamingResponse(
                generate(),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no",
                },
            )
        else:
            result = await copilot.chat_sync(
                request.session_id,
                request.message
            )
            return result

    # ============== Workflow-level Copilot Config ==============

    @app.get("/api/workflows/{workflow_id}/copilot/config")
    async def get_workflow_copilot_config(workflow_id: str):
        """
        Get Copilot configuration for a specific workflow.
        Falls back to global config if workflow-specific config doesn't exist.
        """
        from ..copilot import get_copilot_service
        from ..orchestration.workflow import get_workflow_manager

        copilot = get_copilot_service()
        manager = get_workflow_manager()

        # Get workflow to check if it exists
        workflow = await manager.get_workflow(workflow_id)
        if not workflow:
            raise HTTPException(status_code=404, detail="Workflow not found")

        # Try to get workflow-level config
        workflow_config = manager.get_workflow_copilot_config(workflow_id)

        if workflow_config:
            # Return workflow-level config
            config = copilot.format_config(workflow_config)
            config['is_workflow_level'] = True
            return config
        else:
            # Return global config as fallback
            config = copilot.get_config()
            config['is_workflow_level'] = False
            return config

    @app.post("/api/workflows/{workflow_id}/copilot/config")
    async def update_workflow_copilot_config(
        workflow_id: str,
        request: CopilotConfigRequest
    ):
        """
        Update Copilot configuration for a specific workflow.
        This overrides the global configuration for this workflow only.
        """
        from ..copilot import get_copilot_service
        from ..orchestration.workflow import get_workflow_manager

        copilot = get_copilot_service()
        manager = get_workflow_manager()

        # Get workflow to check if it exists
        workflow = await manager.get_workflow(workflow_id)
        if not workflow:
            raise HTTPException(status_code=404, detail="Workflow not found")

        # Save workflow-level config
        workflow_config = {
            'provider': request.provider,
            'model': request.model,
            'api_key': request.api_key,
            'base_url': request.base_url,
        }

        # Remove None values
        workflow_config = {k: v for k, v in workflow_config.items() if v is not None}

        await manager.set_workflow_copilot_config(workflow_id, workflow_config)

        # Return formatted config
        config = copilot.format_config(workflow_config)
        config['is_workflow_level'] = True

        return {
            "status": "updated",
            "config": config,
        }

    @app.delete("/api/workflows/{workflow_id}/copilot/config")
    async def delete_workflow_copilot_config(workflow_id: str):
        """
        Delete workflow-specific Copilot configuration.
        After deletion, the workflow will use the global configuration.
        """
        from ..orchestration.workflow import get_workflow_manager

        manager = get_workflow_manager()

        # Get workflow to check if it exists
        workflow = await manager.get_workflow(workflow_id)
        if not workflow:
            raise HTTPException(status_code=404, detail="Workflow not found")

        await manager.delete_workflow_copilot_config(workflow_id)

        return {"status": "deleted"}

    # ============== Artifact Factory Endpoints ==============

    @app.post("/api/artifacts/decide", summary="评估并创建生成候选")
    async def decide_artifact(request: ArtifactDecisionRequest):
        from ..artifacts import get_artifact_factory_service

        factory = get_artifact_factory_service()
        try:
            candidate = await factory.decide_and_create_candidate(
                user_id=request.user_id,
                source_session_id=request.source_session_id,
                parent_candidate_id=request.parent_candidate_id,
                task_summary=request.task_summary,
                repeat_count=request.repeat_count,
                tool_call_count=request.tool_call_count,
                unique_tool_count=request.unique_tool_count,
                parallel_branches=request.parallel_branches,
                requires_long_running=request.requires_long_running,
                has_manual_steps=request.has_manual_steps,
                failure_rate=request.failure_rate,
                high_risk=request.high_risk,
                metadata=request.metadata,
            )
        except ValueError as exc:
            detail = str(exc)
            status_code = 404 if "not found" in detail else 400
            raise HTTPException(status_code=status_code, detail=detail)
        return candidate.model_dump()

    @app.post("/api/artifacts/decide/from-trajectory", summary="基于真实执行轨迹自动提取信号并创建候选")
    async def decide_artifact_from_trajectory(request: ArtifactDecisionFromTrajectoryRequest):
        from ..artifacts import get_artifact_factory_service
        from ..copilot import get_copilot_service

        copilot = get_copilot_service()
        session = await copilot.get_session(request.session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")

        all_sessions = await copilot.session_manager.list_sessions()
        all_user_messages: List[str] = []
        for item in all_sessions:
            for message in item.messages:
                if message.role == "user" and message.content.strip():
                    all_user_messages.append(message.content)

        messages = [
            {
                "role": msg.role,
                "content": msg.content,
                "tool_calls": msg.tool_calls or [],
                "tool_results": msg.tool_results or [],
            }
            for msg in session.messages
        ]

        tool_execution_audit: List[Dict[str, Any]] = list(request.tool_execution_audit)
        metadata_audit = request.metadata.get("tool_execution_audit")
        if isinstance(metadata_audit, list):
            tool_execution_audit.extend(
                item for item in metadata_audit if isinstance(item, dict)
            )

        approval_results: List[Dict[str, Any]] = list(request.approval_results)
        metadata_approval = request.metadata.get("approval_results")
        if isinstance(metadata_approval, list):
            approval_results.extend(
                item for item in metadata_approval if isinstance(item, dict)
            )
        for msg in messages:
            for result in msg.get("tool_results") or []:
                if not isinstance(result, dict):
                    continue
                result_metadata = result.get("metadata") or {}
                if not isinstance(result_metadata, dict):
                    continue
                approval_status = str(
                    result_metadata.get("approval_status", "")
                ).lower()
                if approval_status in {"pending", "approved", "denied"}:
                    approval_results.append(
                        {
                            "status": approval_status,
                            "approval_id": result_metadata.get("approval_id"),
                            "tool_call_id": result.get("tool_call_id"),
                        }
                    )

        factory = get_artifact_factory_service()
        candidate = await factory.decide_from_execution_trajectory(
            user_id=request.user_id,
            source_session_id=request.session_id,
            messages=messages,
            all_sessions_user_messages=all_user_messages,
            tool_execution_audit=tool_execution_audit,
            approval_results=approval_results,
            metadata=request.metadata,
        )
        return candidate.model_dump()

    @app.get("/api/artifacts/candidates", summary="列出生成候选")
    async def list_artifact_candidates(
        status: Optional[ArtifactCandidateStatus] = None,
        user_id: Optional[str] = None,
    ):
        from ..artifacts import get_artifact_factory_service

        factory = get_artifact_factory_service()
        candidates = await factory.list_candidates(status=status, user_id=user_id)
        return [c.model_dump() for c in candidates]

    @app.get(
        "/api/artifacts/candidates/{candidate_id}/lineage",
        summary="查询产物版本系谱",
    )
    async def get_artifact_candidate_lineage(candidate_id: str):
        from ..artifacts import get_artifact_factory_service

        factory = get_artifact_factory_service()
        try:
            return await factory.get_candidate_lineage(candidate_id)
        except ValueError:
            raise HTTPException(status_code=404, detail="Candidate not found")

    @app.get(
        "/api/artifacts/candidates/{candidate_id}/decision-explanations",
        summary="查询候选的决策解释记录",
    )
    async def list_artifact_candidate_decision_explanations(candidate_id: str):
        from ..artifacts import get_artifact_factory_service

        factory = get_artifact_factory_service()
        try:
            explanations = await factory.get_decision_explanations(candidate_id)
        except ValueError:
            raise HTTPException(status_code=404, detail="Candidate not found")
        return {
            "candidate_id": candidate_id,
            "count": len(explanations),
            "items": explanations,
        }

    @app.post("/api/artifacts/candidates/{candidate_id}/approve", summary="审批并物化候选")
    async def approve_artifact_candidate(candidate_id: str, request: ArtifactApproveRequest):
        from ..artifacts import get_artifact_factory_service

        factory = get_artifact_factory_service()
        try:
            candidate = await factory.approve_and_materialize(
                candidate_id=candidate_id,
                approver=request.approver,
                bind_agent_id=request.bind_agent_id,
            )
        except ValueError:
            raise HTTPException(status_code=404, detail="Candidate not found")
        return candidate.model_dump()

    @app.post("/api/artifacts/candidates/{candidate_id}/metrics", summary="采集产物效果指标")
    async def collect_artifact_candidate_metrics(
        candidate_id: str,
        request: ArtifactMetricsCollectRequest,
    ):
        from ..artifacts import get_artifact_factory_service

        factory = get_artifact_factory_service()
        try:
            candidate = await factory.collect_effect_metrics(
                candidate_id=candidate_id,
                metrics=request.metrics,
                reporter=request.reporter,
            )
        except ValueError as exc:
            detail = str(exc)
            status_code = 404 if "not found" in detail else 400
            raise HTTPException(status_code=status_code, detail=detail)
        return candidate.model_dump()

    @app.get("/api/artifacts/dashboard", summary="获取产物指标看板")
    async def get_artifact_dashboard(
        user_id: Optional[str] = None,
        include_candidates: int = 20,
    ):
        from ..artifacts import get_artifact_factory_service

        factory = get_artifact_factory_service()
        include_candidates = max(1, min(include_candidates, 100))
        return await factory.get_metrics_dashboard(
            user_id=user_id,
            include_candidates=include_candidates,
        )

    @app.get("/api/artifacts/alerts", summary="查询产物告警事件")
    async def list_artifact_alert_events(
        user_id: Optional[str] = None,
        candidate_id: Optional[str] = None,
        severity: Optional[str] = None,
        limit: int = 100,
    ):
        from ..artifacts import get_artifact_factory_service

        factory = get_artifact_factory_service()
        limit = max(1, min(limit, 500))
        events = await factory.list_alert_events(
            user_id=user_id,
            candidate_id=candidate_id,
            severity=severity,
            limit=limit,
        )
        return {
            "count": len(events),
            "items": events,
        }

    @app.post(
        "/api/artifacts/candidates/{candidate_id}/rollout/decide",
        summary="自动升级与回滚决策",
    )
    async def decide_artifact_candidate_rollout(
        candidate_id: str,
        request: ArtifactRolloutDecisionRequest,
    ):
        from ..artifacts import get_artifact_factory_service

        factory = get_artifact_factory_service()
        try:
            return await factory.decide_rollout_action(
                candidate_id=candidate_id,
                min_sample_size=request.min_sample_size,
                upgrade_success_rate=request.upgrade_success_rate,
                rollback_error_rate=request.rollback_error_rate,
                max_latency_p95_ms=request.max_latency_p95_ms,
                min_success_rate_for_rollback=request.min_success_rate_for_rollback,
                auto_apply=request.auto_apply,
                operator=request.operator,
            )
        except ValueError as exc:
            detail = str(exc)
            status_code = 404 if "not found" in detail else 400
            raise HTTPException(status_code=status_code, detail=detail)

    @app.post(
        "/api/artifacts/candidates/{candidate_id}/rollout/transition",
        summary="灰度状态流转",
    )
    async def transition_artifact_candidate_rollout(
        candidate_id: str,
        request: ArtifactRolloutTransitionRequest,
    ):
        from ..artifacts import get_artifact_factory_service

        factory = get_artifact_factory_service()
        try:
            candidate = await factory.transition_rollout_status(
                candidate_id=candidate_id,
                target_status=request.target_status,
                operator=request.operator,
                reason=request.reason,
                metadata=request.metadata,
                freeze_window_minutes=request.freeze_window_minutes,
                manual_override=request.manual_override,
                override_reason=request.override_reason,
            )
        except ValueError as exc:
            detail = str(exc)
            status_code = 404 if "not found" in detail else 400
            raise HTTPException(status_code=status_code, detail=detail)
        return candidate.model_dump()

    @app.post(
        "/api/artifacts/candidates/{candidate_id}/ab-routing/config",
        summary="配置 A/B 灰度路由策略",
    )
    async def configure_artifact_candidate_ab_routing(
        candidate_id: str,
        request: ArtifactABRoutingConfigRequest,
    ):
        from ..artifacts import get_artifact_factory_service

        factory = get_artifact_factory_service()
        try:
            candidate = await factory.configure_ab_routing(
                candidate_id=candidate_id,
                enabled=request.enabled,
                control_ratio=request.control_ratio,
                salt=request.salt,
                operator=request.operator,
                notes=request.notes,
            )
        except ValueError as exc:
            detail = str(exc)
            status_code = 404 if "not found" in detail else 400
            raise HTTPException(status_code=status_code, detail=detail)
        return candidate.model_dump()

    @app.post(
        "/api/artifacts/candidates/{candidate_id}/ab-routing/route",
        summary="执行 A/B 灰度路由",
    )
    async def route_artifact_candidate_ab_bucket(
        candidate_id: str,
        request: ArtifactABRoutingRouteRequest,
    ):
        from ..artifacts import get_artifact_factory_service

        factory = get_artifact_factory_service()
        try:
            return await factory.route_candidate_ab_bucket(
                candidate_id=candidate_id,
                subject_key=request.subject_key,
                force_bucket=request.force_bucket,
                force_target_candidate_id=request.force_target_candidate_id,
            )
        except ValueError as exc:
            detail = str(exc)
            status_code = 404 if "not found" in detail else 400
            raise HTTPException(status_code=status_code, detail=detail)

    @app.get(
        "/api/artifacts/candidates/{candidate_id}/rollout/freeze",
        summary="查询回滚冻结窗口状态",
    )
    async def get_artifact_candidate_rollback_freeze(candidate_id: str):
        from ..artifacts import get_artifact_factory_service

        factory = get_artifact_factory_service()
        try:
            return await factory.get_rollback_freeze(candidate_id)
        except ValueError:
            raise HTTPException(status_code=404, detail="Candidate not found")

    @app.post(
        "/api/artifacts/candidates/{candidate_id}/rollout/freeze/override",
        summary="人工 override 回滚冻结窗口",
    )
    async def override_artifact_candidate_rollback_freeze(
        candidate_id: str,
        request: ArtifactRollbackFreezeOverrideRequest,
    ):
        from ..artifacts import get_artifact_factory_service

        factory = get_artifact_factory_service()
        try:
            candidate = await factory.override_rollback_freeze(
                candidate_id=candidate_id,
                operator=request.operator,
                reason=request.reason,
            )
        except ValueError:
            raise HTTPException(status_code=404, detail="Candidate not found")
        return candidate.model_dump()

    @app.post(
        "/api/artifacts/learning/cycle",
        summary="周期学习：轨迹聚类发现候选 + 自动修订触发",
    )
    async def run_artifact_periodic_learning_cycle(
        request: ArtifactPeriodicLearningRequest,
    ):
        from ..artifacts import get_artifact_factory_service
        from ..copilot import get_copilot_service

        copilot = get_copilot_service()
        sessions = await copilot.session_manager.list_sessions()
        sessions_sorted = sorted(
            sessions,
            key=lambda s: s.updated_at,
            reverse=True,
        )
        max_sessions = max(1, int(request.max_sessions))
        if max_sessions:
            sessions_sorted = sessions_sorted[:max_sessions]

        trajectories: List[Dict[str, Any]] = []
        for session in sessions_sorted:
            session_user_id = str((session.metadata or {}).get("user_id", "")).strip()
            if request.user_id and session_user_id != request.user_id:
                continue
            if not session.messages:
                continue
            trajectories.append(
                {
                    "session_id": session.session_id,
                    "user_id": session_user_id or request.user_id or "default",
                    "messages": [
                        {
                            "role": msg.role,
                            "content": msg.content,
                            "tool_calls": msg.tool_calls or [],
                            "tool_results": msg.tool_results or [],
                        }
                        for msg in session.messages
                    ],
                    "updated_at": session.updated_at.isoformat(),
                }
            )

        factory = get_artifact_factory_service()
        result = await factory.run_periodic_learning_cycle(
            trajectories=trajectories,
            user_id=request.user_id,
            min_cluster_size=request.min_cluster_size,
            dry_run=request.dry_run,
            trigger_revision=request.trigger_revision,
            min_revision_samples=request.min_revision_samples,
            revision_cooldown_hours=request.revision_cooldown_hours,
        )
        result["input"] = {
            "session_count": len(trajectories),
            "max_sessions": max_sessions,
            "trigger_revision": request.trigger_revision,
            "dry_run": request.dry_run,
        }
        return result

    # ============== Search Config Endpoints ==============

    @app.get("/api/search/config")
    async def get_search_config():
        """
        Get current search configuration.

        Returns:
        - Current provider and configuration status
        - List of all available providers with their status
        """
        from ..tools import get_search_config
        config = get_search_config()
        return config.to_dict()

    @app.post("/api/search/config")
    async def update_search_config(request: SearchConfigRequest):
        """
        Update search configuration at runtime.

        Supported providers:
        - bing: Microsoft Bing (default, works in China, no API key needed)
        - searxng: Self-hosted meta-search engine (requires base URL)
        - serper: Google Search API (requires API key)
        - brave: Brave Search (requires API key)
        - google: Google Custom Search (requires API key + CX)
        - duckduckgo: Free fallback
        """
        from ..tools import get_search_config
        config = get_search_config()
        await config.update(
            provider=request.provider,
            searxng_base_url=request.searxng_base_url,
            serper_api_key=request.serper_api_key,
            brave_api_key=request.brave_api_key,
            bing_api_key=request.bing_api_key,
            tavily_api_key=request.tavily_api_key,
            google_api_key=request.google_api_key,
            google_cx=request.google_cx,
        )
        return {
            "status": "updated",
            "config": config.to_dict(),
        }

    @app.post("/api/search/test")
    async def test_search(query: str = "AI news", provider: Optional[str] = None):
        """
        Test search with the current configuration.

        Args:
            query: Search query to test
            provider: Optional specific provider to test
        """
        from ..tools import get_system_tool_registry
        registry = get_system_tool_registry()
        result = await registry.execute(
            "web_search",
            query=query,
            count=3,
            locale="zh-CN",
            provider=provider,
        )
        return {"query": query, "provider": provider, "result": result}

    # ============== Email Config Endpoints ==============

    @app.get("/api/email/config")
    async def get_email_config():
        """
        Get current email configuration.

        Returns:
        - Active email method (resend, smtp, or none)
        - Configuration status for both Resend API and SMTP
        """
        try:
            from ..tools.email import get_email_config
            config = get_email_config()
            return config.to_dict()
        except ImportError:
            return {
                "preferred_method": "auto",
                "active_method": "none",
                "resend": {"configured": False, "api_key_preview": "", "from": ""},
                "smtp": {
                    "configured": False,
                    "host": "smtp.gmail.com",
                    "port": 587,
                    "user": "",
                    "password_preview": "",
                    "from": "",
                    "use_tls": True,
                },
                "error": "Email module not available (missing aiosmtplib dependency)",
            }

    @app.post("/api/email/config")
    async def update_email_config(request: EmailConfigRequest):
        """
        Update email configuration at runtime.

        Supported methods:
        - resend: Resend API (recommended for custom domains like Cloudflare)
        - smtp: Traditional SMTP (Gmail, QQ Mail, 163, etc.)
        """
        try:
            from ..tools.email import get_email_config
            config = get_email_config()
            await config.update(
                preferred_method=request.preferred_method,
                resend_api_key=request.resend_api_key,
                resend_from=request.resend_from,
                smtp_host=request.smtp_host,
                smtp_port=request.smtp_port,
                smtp_user=request.smtp_user,
                smtp_password=request.smtp_password,
                smtp_from=request.smtp_from,
                smtp_use_tls=request.smtp_use_tls,
            )
            return {
                "status": "updated",
                "config": config.to_dict(),
            }
        except ImportError:
            raise HTTPException(
                status_code=500,
                detail="Email module not available (missing aiosmtplib dependency)"
            )

    @app.post("/api/email/test")
    async def test_email(request: TestEmailRequest):
        """
        Send a test email to verify configuration.

        Args:
            to: Email address to send test email to
        """
        from ..tools import get_system_tool_registry
        registry = get_system_tool_registry()
        result = await registry.execute(
            "send_email",
            to=request.to,
            subject="Proton Email Test",
            body="This is a test email from Proton Agent Platform.\n\nIf you receive this, your email configuration is working correctly!",
            html=False,
        )
        if result.startswith("Error"):
            return {"status": "error", "message": result}
        return {"status": "success", "message": result}

    # ============== Publishing Endpoints ==============

    @app.post("/api/workflows/{workflow_id}/publish")
    async def publish_workflow(workflow_id: str, request: PublishRequest):
        """Publish a workflow as an API service."""
        manager = get_workflow_manager()

        try:
            result = await manager.publish_workflow(
                workflow_id,
                version=request.version,
                description=request.description,
                tags=request.tags
            )

            # Auto-add to default portal if auto_include_published is enabled
            try:
                from ..portal import get_portal_manager
                portal_mgr = get_portal_manager()
                default_portal = await portal_mgr.get_default_portal()
                if (
                    default_portal
                    and default_portal.auto_include_published
                    and workflow_id not in default_portal.workflow_ids
                ):
                    updated_ids = list(default_portal.workflow_ids) + [workflow_id]
                    await portal_mgr.update_portal(
                        default_portal.id, {"workflow_ids": updated_ids}
                    )
                    logger.info(
                        f"Auto-added workflow {workflow_id} to default portal {default_portal.id}"
                    )
            except Exception as e:
                logger.warning(f"Failed to auto-add workflow to default portal: {e}")

            return {
                "workflow_id": workflow_id,
                "api_key": result.api_key,
                "version": result.version,
                "endpoint": f"/api/published/{result.api_key}/run",
            }
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))

    @app.post("/api/workflows/{workflow_id}/unpublish")
    async def unpublish_workflow(workflow_id: str):
        """Unpublish a workflow."""
        manager = get_workflow_manager()
        success = await manager.unpublish_workflow(workflow_id)

        if not success:
            raise HTTPException(status_code=404, detail="Workflow not found or not published")

        return {"status": "unpublished", "workflow_id": workflow_id}

    @app.get("/api/published")
    async def list_published_workflows():
        """List all published workflows."""
        manager = get_workflow_manager()
        return await manager.list_published()

    @app.post("/api/published/{api_key}/run")
    async def run_published_workflow(api_key: str, request: RunWorkflowRequest):
        """Execute a published workflow via API key."""
        manager = get_workflow_manager()
        workflow = await manager.get_by_api_key(api_key)

        if not workflow:
            raise HTTPException(status_code=404, detail="Workflow not found or not published")

        if request.stream:
            async def generate():
                async for event in workflow.run_stream_with_events(request.message):
                    event_data = event.model_dump(exclude_none=True)
                    yield f"data: {json.dumps(event_data, ensure_ascii=False)}\n\n"
                yield "data: [DONE]\n\n"

            return StreamingResponse(
                generate(),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no",
                },
            )

        result = await workflow.run(request.message)

        output = None
        if result.response and result.response.messages:
            output = "\n".join(m.content for m in result.response.messages)

        return ExecutionResponse(
            workflow_id=result.workflow_id,
            execution_id=result.execution_id,
            state=result.state.value,
            output=output,
            error=result.error,
            duration_ms=result.duration_ms,
        )

    # ============== Gateway Endpoint ==============

    @app.post("/api/gateway/route")
    async def gateway_route(request: GatewayRequest):
        """
        Unified entry point that routes to appropriate workflow.
        Uses a router workflow with conditional routing to sub-workflows.
        """
        manager = get_workflow_manager()
        router_workflow = await manager.get_gateway_router()

        if not router_workflow:
            raise HTTPException(
                status_code=404,
                detail="No gateway router configured. Publish a workflow with 'gateway' tag."
            )

        if request.stream:
            async def generate():
                async for event in router_workflow.run_stream_with_events(request.message):
                    event_data = event.model_dump(exclude_none=True)
                    yield f"data: {json.dumps(event_data, ensure_ascii=False)}\n\n"
                yield "data: [DONE]\n\n"

            return StreamingResponse(
                generate(),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no",
                },
            )

        result = await router_workflow.run(request.message)

        output = None
        if result.response and result.response.messages:
            output = "\n".join(m.content for m in result.response.messages)

        return {
            "workflow_id": result.workflow_id,
            "execution_id": result.execution_id,
            "state": result.state.value,
            "output": output,
            "error": result.error,
            "duration_ms": result.duration_ms,
        }

    # ============== Super Portal Endpoints ==============

    class CreatePortalRequest(BaseModel):
        """Request to create a Super Portal."""
        name: str
        description: str = ""
        workflow_ids: List[str] = Field(default_factory=list)
        provider: str = "openai"
        model: str = "gpt-4"
        api_key: Optional[str] = None
        base_url: Optional[str] = None
        memory_enabled: bool = True
        global_memory_enabled: bool = False
        memory_provider: str = "mempalace"
        mempalace_palace_path: Optional[str] = None
        mempalace_command: str = "python"
        mempalace_args: List[str] = Field(default_factory=lambda: ["-m", "mempalace.mcp_server"])
        mempalace_env: Dict[str, str] = Field(default_factory=dict)
        mempalace_wing_strategy: str = "per_user"
        mempalace_default_room: str = "general"
        is_default: bool = False
        auto_include_published: bool = False
        fallback_to_copilot: bool = True
        backbone_system_prompt: str = (
            "You are a helpful AI assistant. Answer the user's question directly, "
            "clearly, and concisely. Use Markdown formatting where appropriate."
        )

    class PortalChatRequest(BaseModel):
        """Request to chat with a Super Portal."""
        session_id: str
        message: str
        user_id: str = "default"
        stream: bool = True

    class PortalSafetyScanRequest(BaseModel):
        """Manual pre-generation safety scan request."""
        user_message: str
        intent: str = ""
        workflow_results: Dict[str, str] = Field(default_factory=dict)
        memory_snapshot: str = ""
        user_id: str = "default"

    @app.post("/api/portals", summary="创建超级入口")
    async def create_portal(request: CreatePortalRequest):
        """
        创建超级入口，将多个已发布工作流聚合为一个智能统一入口。

        超级入口具备：
        - 需求理解：自动拆解用户意图，路由到合适的工作流
        - 长期记忆：跨会话记住用户偏好和关键信息
        - 历史会话：支持多轮对话上下文
        - 结果综合：将多个工作流结果整合为连贯回复
        """
        from ..portal import get_portal_manager
        mgr = get_portal_manager()
        config = await mgr.create_portal(
            name=request.name,
            description=request.description,
            workflow_ids=request.workflow_ids,
            provider=request.provider,
            model=request.model,
            api_key=request.api_key,
            base_url=request.base_url,
            memory_enabled=request.memory_enabled,
            global_memory_enabled=request.global_memory_enabled,
            memory_provider=request.memory_provider,
            mempalace_palace_path=request.mempalace_palace_path,
            mempalace_command=request.mempalace_command,
            mempalace_args=request.mempalace_args,
            mempalace_env=request.mempalace_env,
            mempalace_wing_strategy=request.mempalace_wing_strategy,
            mempalace_default_room=request.mempalace_default_room,
            is_default=request.is_default,
            auto_include_published=request.auto_include_published,
            fallback_to_copilot=request.fallback_to_copilot,
            backbone_system_prompt=request.backbone_system_prompt,
        )
        return config.model_dump()

    @app.get("/api/portals", summary="列出所有超级入口")
    async def list_portals():
        """列出所有超级入口及其配置。不包含默认的 Root Portal。"""
        from ..portal import get_portal_manager
        mgr = get_portal_manager()
        portals = await mgr.list_portals()
        # 根入口(Root Portal)不展示在超级入口列表中
        portals = [p for p in portals if not p.is_default]
        return [p.model_dump() for p in portals]

    @app.get("/api/portals/default", summary="获取默认 Root Portal")
    async def get_default_portal():
        """
        获取系统默认 Root Portal（没有则自动创建）。

        Root Portal 是系统默认入口，自带通用 AI 对话能力（Backbone Agent），
        无需绑定工作流即可直接对话。
        """
        from ..portal import get_portal_manager
        mgr = get_portal_manager()
        config = await mgr.ensure_default_portal()
        return config.model_dump()

    @app.get("/api/portals/{portal_id}", summary="获取超级入口详情")
    async def get_portal(portal_id: str):
        """获取指定超级入口的完整配置。"""
        from ..portal import get_portal_manager
        mgr = get_portal_manager()
        config = await mgr.get_portal(portal_id)
        if not config:
            raise HTTPException(status_code=404, detail="Portal not found")
        return config.model_dump()

    @app.put("/api/portals/{portal_id}", summary="更新超级入口配置")
    async def update_portal(portal_id: str, updates: Dict[str, Any]):
        """
        更新超级入口配置。

        可更新字段：name, description, workflow_ids, provider, model,
        api_key, base_url, memory_enabled, global_memory_enabled,
        max_session_messages, session_ttl_hours, public
        """
        from ..portal import get_portal_manager
        mgr = get_portal_manager()
        config = await mgr.update_portal(portal_id, updates)
        if not config:
            raise HTTPException(status_code=404, detail="Portal not found")
        return config.model_dump()

    @app.delete("/api/portals/{portal_id}", summary="删除超级入口")
    async def delete_portal(portal_id: str):
        """删除超级入口（不影响绑定的工作流）。"""
        from ..portal import get_portal_manager
        mgr = get_portal_manager()
        ok = await mgr.delete_portal(portal_id)
        if not ok:
            raise HTTPException(status_code=404, detail="Portal not found")
        return {"status": "deleted", "id": portal_id}

    @app.post("/api/portals/{portal_id}/sessions", summary="创建超级入口会话")
    async def create_portal_session(portal_id: str, body: Dict[str, Any] = {}):
        """
        创建新的对话会话。

        建议在开始与超级入口对话前调用此接口，获取 session_id 后用于后续对话。
        """
        from ..portal import get_portal_manager
        mgr = get_portal_manager()
        svc = await mgr.get_service(portal_id)
        if not svc:
            raise HTTPException(status_code=404, detail="Portal not found")
        session = await svc.create_session(
            user_id=body.get("user_id", "default"),
            metadata=body.get("metadata"),
        )
        return {"session_id": session.session_id, "portal_id": portal_id}

    @app.get("/api/portals/{portal_id}/sessions/{session_id}", summary="获取会话历史")
    async def get_portal_session(portal_id: str, session_id: str):
        """获取指定会话的完整对话历史。"""
        from ..portal import get_portal_manager
        mgr = get_portal_manager()
        svc = await mgr.get_service(portal_id)
        if not svc:
            raise HTTPException(status_code=404, detail="Portal not found")
        session = await svc.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        return session.model_dump()

    @app.get("/api/portals/{portal_id}/sessions/search", summary="检索历史会话片段")
    async def search_portal_sessions(
        portal_id: str,
        query: str,
        user_id: str = "default",
        top_k: int = 8,
        exclude_session_id: Optional[str] = None,
    ):
        """
        按关键词检索该超级入口下指定用户的历史会话片段。

        适用于跨会话回忆：当当前会话里缺少上下文时，可主动检索历史讨论内容。
        """
        from ..portal import get_portal_manager
        mgr = get_portal_manager()
        svc = await mgr.get_service(portal_id)
        if not svc:
            raise HTTPException(status_code=404, detail="Portal not found")
        return await svc.search_sessions(
            user_id=user_id,
            query=query,
            top_k=top_k,
            exclude_session_id=exclude_session_id,
        )

    @app.post("/api/portals/{portal_id}/chat", summary="与超级入口对话（SSE流）")
    async def portal_chat(portal_id: str, request: PortalChatRequest):
        """
        向超级入口发送消息，支持 SSE 流式响应。

        事件类型（type 字段）：
        - intent_understood: 意图解析完成，包含将调用的工作流列表
        - workflow_dispatch_start: 开始调用某个工作流
        - workflow_dispatch_result: 工作流返回结果
        - synthesis_start: 开始综合最终回答
        - content: 流式文本内容（delta 字段）
        - memory_updated: 记忆已更新
        - complete: 本轮对话完成
        - error: 发生错误
        """
        from ..portal import get_portal_manager
        mgr = get_portal_manager()
        svc = await mgr.get_service(portal_id)
        if not svc:
            raise HTTPException(status_code=404, detail="Portal not found")

        if request.stream:
            async def generate():
                async for event in svc.chat(
                    session_id=request.session_id,
                    user_message=request.message,
                    user_id=request.user_id,
                    stream=True,
                ):
                    data = event.model_dump(exclude_none=True)
                    if "timestamp" in data:
                        data["timestamp"] = data["timestamp"].isoformat()
                    yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
                yield "data: [DONE]\n\n"

            return StreamingResponse(
                generate(),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no",
                },
            )
        else:
            events = []
            content_parts = []
            async for event in svc.chat(
                session_id=request.session_id,
                user_message=request.message,
                user_id=request.user_id,
                stream=False,
            ):
                d = event.model_dump(exclude_none=True)
                if "timestamp" in d:
                    d["timestamp"] = d["timestamp"].isoformat()
                events.append(d)
                if event.delta:
                    content_parts.append(event.delta)
            return {
                "content": "".join(content_parts),
                "events": events,
            }

    @app.post(
        "/api/portals/access/{access_key}/chat",
        summary="通过 API Key 访问超级入口（对外公开接口）",
    )
    async def portal_chat_by_key(access_key: str, request: PortalChatRequest):
        """
        使用超级入口的访问密钥（api_key_access）直接对话，
        适合对外发布后的第三方调用场景。
        """
        from ..portal import get_portal_manager
        mgr = get_portal_manager()
        config = await mgr.get_by_access_key(access_key)
        if not config:
            raise HTTPException(status_code=404, detail="Portal not found or invalid key")
        return await portal_chat(config.id, request)

    @app.get("/api/portals/{portal_id}/memories", summary="查看用户记忆")
    async def get_portal_memories(
        portal_id: str,
        user_id: str = "default",
        query: str = "",
        top_k: int = 20,
        min_confidence: float = 0.0,
        confidence_tier: Optional[str] = None,
        include_conflicted: bool = True,
        session_id: Optional[str] = None,
    ):
        """
        查看超级入口为指定用户积累的长期记忆。

        支持通过 query 做关键词语义检索，返回最相关的 top_k 条。
        """
        from ..portal import get_portal_manager
        mgr = get_portal_manager()
        svc = await mgr.get_service(portal_id)
        if not svc:
            raise HTTPException(status_code=404, detail="Portal not found")
        memories = await svc.get_memories(
            user_id=user_id,
            query=query,
            top_k=top_k,
            min_confidence=min_confidence,
            confidence_tier=confidence_tier,
            include_conflicted=include_conflicted,
            session_id=session_id,
        )
        return [m.model_dump() for m in memories]

    @app.post("/api/portals/{portal_id}/safety/scan", summary="生成前安全扫描")
    async def portal_pre_generation_safety_scan(portal_id: str, request: PortalSafetyScanRequest):
        """对当前上下文执行生成前安全扫描，返回是否会触发拦截。"""
        from ..portal import get_portal_manager
        mgr = get_portal_manager()
        svc = await mgr.get_service(portal_id)
        if not svc:
            raise HTTPException(status_code=404, detail="Portal not found")
        memories = await svc.get_memories(
            user_id=request.user_id,
            query=request.user_message,
            top_k=10,
        )
        result = svc.pre_generation_safety_scan(
            user_query=request.user_message,
            intent=request.intent,
            workflow_results=request.workflow_results,
            memories=memories,
            memory_snapshot=request.memory_snapshot,
        )
        return result.model_dump()

    @app.delete("/api/portals/{portal_id}/memories/{entry_id}", summary="删除单条记忆")
    async def delete_portal_memory(portal_id: str, entry_id: str, user_id: str = "default"):
        """删除指定的记忆条目。"""
        from ..portal import get_portal_manager
        mgr = get_portal_manager()
        svc = await mgr.get_service(portal_id)
        if not svc:
            raise HTTPException(status_code=404, detail="Portal not found")
        ok = await svc.delete_memory(user_id=user_id, entry_id=entry_id)
        return {"deleted": ok, "entry_id": entry_id}

    @app.delete("/api/portals/{portal_id}/memories", summary="清空用户所有记忆")
    async def clear_portal_memories(portal_id: str, user_id: str = "default"):
        """清空指定用户在此超级入口的所有长期记忆。"""
        from ..portal import get_portal_manager
        mgr = get_portal_manager()
        svc = await mgr.get_service(portal_id)
        if not svc:
            raise HTTPException(status_code=404, detail="Portal not found")
        count = await svc.clear_memories(user_id=user_id)
        return {"cleared": count, "user_id": user_id}

    return app


def _get_builtin_templates() -> List[AgentTemplate]:
    """Get built-in agent templates."""
    from uuid import uuid4

    templates = [
        AgentTemplate(
            id="tpl-assistant",
            name="General Assistant",
            description="A helpful AI assistant for general conversations and tasks",
            category="assistant",
            icon="robot",
            is_official=True,
            definition=BuiltinAgentDefinition(
                name="Assistant",
                description="A helpful AI assistant",
                model="gpt-4",
                temperature=0.7,
                system_prompt="""You are a helpful AI assistant. You provide clear, accurate,
and helpful responses to user queries. Be concise but thorough.""",
            ),
        ),
        AgentTemplate(
            id="tpl-coder",
            name="Code Assistant",
            description="An AI assistant specialized in programming and code generation",
            category="specialist",
            icon="code",
            is_official=True,
            definition=BuiltinAgentDefinition(
                name="Code Assistant",
                description="Helps with programming tasks",
                model="gpt-4",
                temperature=0.3,
                system_prompt="""You are an expert programmer. Help users with:
- Writing clean, efficient code
- Debugging issues
- Explaining code concepts
- Code reviews and improvements

Always provide working code examples when relevant.""",
                output_format=OutputFormat(format_type="markdown"),
            ),
        ),
        AgentTemplate(
            id="tpl-router",
            name="Task Router",
            description="Routes user requests to appropriate specialist agents",
            category="router",
            icon="share",
            is_official=True,
            definition=BuiltinAgentDefinition(
                name="Task Router",
                description="Routes tasks to specialists",
                model="gpt-4",
                temperature=0.2,
                system_prompt="""You are a task router. Analyze user requests and determine
which specialist should handle them. Available specialists will be provided in context.
Respond with the specialist name and a brief handoff message.""",
            ),
        ),
        AgentTemplate(
            id="tpl-analyst",
            name="Data Analyst",
            description="Analyzes data and provides insights",
            category="specialist",
            icon="chart",
            is_official=True,
            definition=BuiltinAgentDefinition(
                name="Data Analyst",
                description="Analyzes data and provides insights",
                model="gpt-4",
                temperature=0.5,
                system_prompt="""You are a data analyst. Help users:
- Understand their data
- Identify patterns and trends
- Generate insights
- Create visualizations descriptions

Be precise with numbers and always cite your sources.""",
            ),
        ),
        AgentTemplate(
            id="tpl-writer",
            name="Content Writer",
            description="Creates and edits written content",
            category="specialist",
            icon="edit",
            is_official=True,
            definition=BuiltinAgentDefinition(
                name="Content Writer",
                description="Creates and edits written content",
                model="gpt-4",
                temperature=0.8,
                system_prompt="""You are a professional content writer. Help users:
- Write compelling copy
- Edit and improve existing content
- Adapt tone and style
- Create various content formats

Focus on clarity, engagement, and the target audience.""",
            ),
        ),
        AgentTemplate(
            id="tpl-customer-support",
            name="Customer Support Agent",
            description="Handles customer inquiries and support requests",
            category="specialist",
            icon="headset",
            is_official=True,
            definition=BuiltinAgentDefinition(
                name="Support Agent",
                description="Customer support specialist",
                model="gpt-4",
                temperature=0.5,
                system_prompt="""You are a friendly and professional customer support agent.
- Listen carefully to customer concerns
- Provide clear solutions
- Be empathetic and patient
- Escalate complex issues when needed

Always maintain a helpful and positive tone.""",
            ),
        ),
        # ============== 旅游业务分析 Agent 模板 ==============
        AgentTemplate(
            id="tpl-travel-coordinator",
            name="旅游顾问主管",
            description="旅游业务协调员，负责分配任务给专业顾问团队，最终生成规划文档",
            category="router",
            icon="compass",
            is_official=True,
            definition=BuiltinAgentDefinition(
                name="旅游顾问主管",
                description="协调旅游规划团队，根据用户需求分配任务，整合专家输出，生成规划文档",
                model="gpt-4",
                temperature=0.3,
                system_prompt="""你是一位经验丰富的旅游顾问主管，负责协调一个专业的旅游规划团队。

## 你的团队成员
1. **行程规划师** - 负责设计旅行路线和日程安排
2. **酒店专家** - 负责住宿推荐和预订建议
3. **美食顾问** - 负责当地美食和餐厅推荐
4. **预算分析师** - 负责费用估算和省钱建议
5. **当地文化专家** - 负责文化礼仪和旅行贴士

## 你的工作模式
你将经历两个阶段：

### 第一阶段：分析需求
当收到用户的旅行咨询时，你需要：
1. 理解用户需求（目的地、时间、人数、预算、偏好等）
2. 简要说明你将如何安排团队协作
3. 告知用户你正在召集专家团队

### 第二阶段：整合输出
你会收到各专家的输出（以 "=== XXX 的输出 ===" 格式呈现），此时你需要：
1. 整合所有专家的建议，形成连贯一致的旅行方案
2. 解决任何冲突或不一致的地方
3. 使用 file_write 工具生成完整的规划文档
4. 向用户呈现最终方案并告知文件保存路径

## 文档生成规则
调用 file_write 时：
- 使用相对路径：`旅行规划_目的地_日期.md`
- 使用 Markdown 格式，结构清晰
- 包含章节：基本信息、每日行程、住宿推荐、美食推荐、预算明细、文化贴士、出行清单

请用专业、友好的方式与用户沟通，确保提供高质量的旅行建议。""",
                system_tools=["file_write"],
                output_format=OutputFormat(format_type="markdown"),
            ),
        ),
        AgentTemplate(
            id="tpl-travel-itinerary",
            name="行程规划师",
            description="专业设计旅行路线和日程安排",
            category="specialist",
            icon="map",
            is_official=True,
            definition=BuiltinAgentDefinition(
                name="行程规划师",
                description="设计最优旅行路线和每日行程",
                model="gpt-4",
                temperature=0.5,
                system_prompt="""你是一位专业的行程规划师，擅长设计旅行路线和日程安排。

你的职责：
1. 根据用户的时间和目的地，规划最优路线
2. 考虑景点之间的距离和交通方式
3. 安排合理的游览时间，避免行程过于紧张
4. 考虑季节、天气、节假日等因素
5. 提供备选方案以应对意外情况

输出格式：
- 每天的行程安排（时间、地点、活动）
- 交通方式建议
- 预计游览时长
- 特别提醒事项

请确保行程既充实又轻松，让用户有最佳的旅行体验。""",
                output_format=OutputFormat(format_type="markdown"),
            ),
        ),
        AgentTemplate(
            id="tpl-travel-hotel",
            name="酒店专家",
            description="提供住宿推荐和预订建议",
            category="specialist",
            icon="building",
            is_official=True,
            definition=BuiltinAgentDefinition(
                name="酒店专家",
                description="根据需求推荐最佳住宿选择",
                model="gpt-4",
                temperature=0.5,
                system_prompt="""你是一位酒店住宿专家，熟悉全球各地的住宿选择。

你的职责：
1. 根据用户预算推荐合适的住宿
2. 考虑位置便利性（靠近景点、交通枢纽）
3. 评估酒店设施和服务质量
4. 提供不同档次的选择（经济型、中档、豪华）
5. 介绍特色住宿（民宿、度假村、精品酒店）

推荐时需包含：
- 酒店名称和星级
- 预估价格区间
- 位置优势
- 特色设施
- 预订建议（最佳预订时间、平台推荐）

请根据用户的具体需求（家庭出游、商务出差、蜜月旅行等）提供个性化建议。""",
                output_format=OutputFormat(format_type="markdown"),
            ),
        ),
        AgentTemplate(
            id="tpl-travel-food",
            name="美食顾问",
            description="推荐当地美食和特色餐厅",
            category="specialist",
            icon="utensils",
            is_official=True,
            definition=BuiltinAgentDefinition(
                name="美食顾问",
                description="发现最佳美食体验和餐厅推荐",
                model="gpt-4",
                temperature=0.7,
                system_prompt="""你是一位美食顾问，对世界各地的美食文化有深入了解。

你的职责：
1. 推荐目的地必尝的特色美食
2. 介绍当地知名餐厅和隐藏美食
3. 考虑用户的口味偏好和饮食限制
4. 提供不同价位的选择
5. 分享美食相关的文化背景

推荐内容包括：
- 必尝美食清单及介绍
- 推荐餐厅（档次、价位、特色）
- 当地美食街/夜市推荐
- 用餐礼仪和点餐技巧
- 食物过敏/忌口注意事项

请让美食成为旅行中难忘的体验！""",
                output_format=OutputFormat(format_type="markdown"),
            ),
        ),
        AgentTemplate(
            id="tpl-travel-budget",
            name="预算分析师",
            description="提供详细的费用估算和省钱建议",
            category="specialist",
            icon="calculator",
            is_official=True,
            definition=BuiltinAgentDefinition(
                name="预算分析师",
                description="精确估算旅行费用并提供省钱策略",
                model="gpt-4",
                temperature=0.3,
                system_prompt="""你是一位专业的旅行预算分析师，擅长费用估算和理财规划。

你的职责：
1. 估算各项旅行费用（交通、住宿、餐饮、门票、购物等）
2. 提供详细的预算清单
3. 分析不同方案的性价比
4. 提供省钱技巧和建议
5. 考虑汇率和支付方式

预算报告包括：
- 各项费用明细估算
- 总预算范围（保守/正常/宽裕）
- 省钱小贴士
- 推荐的支付方式和货币兑换建议
- 需要提前预订以获得优惠的项目

请用数据说话，帮助用户做出明智的财务决策。""",
                output_format=OutputFormat(format_type="markdown"),
            ),
        ),
        AgentTemplate(
            id="tpl-travel-culture",
            name="当地文化专家",
            description="提供目的地文化背景和旅行贴士",
            category="specialist",
            icon="globe",
            is_official=True,
            definition=BuiltinAgentDefinition(
                name="当地文化专家",
                description="分享文化知识和实用旅行贴士",
                model="gpt-4",
                temperature=0.6,
                system_prompt="""你是一位文化研究专家，对世界各地的历史文化有深入了解。

你的职责：
1. 介绍目的地的历史文化背景
2. 说明当地的风俗习惯和礼仪禁忌
3. 提供语言沟通小贴士
4. 分享安全注意事项
5. 推荐文化体验活动

内容包括：
- 历史文化简介
- 必知的礼仪和禁忌
- 常用当地语言/短语
- 安全提醒和紧急联系方式
- 推荐的文化体验（节日、表演、手工艺等）
- 购物和纪念品建议

帮助用户做一个有文化素养的旅行者！""",
                output_format=OutputFormat(format_type="markdown"),
            ),
        ),
        # ============== 软件开发团队 Agent 模板 ==============
        AgentTemplate(
            id="tpl-dev-lead",
            name="技术负责人",
            description="软件开发团队负责人，协调开发工作",
            category="router",
            icon="crown",
            is_official=True,
            definition=BuiltinAgentDefinition(
                name="技术负责人",
                description="协调软件开发团队，分配和审核任务",
                model="gpt-4",
                temperature=0.3,
                system_prompt="""你是一位经验丰富的技术负责人，管理一个高效的软件开发团队。

你的团队成员包括：
1. 架构师 - 负责系统设计和技术选型
2. 前端开发 - 负责用户界面开发
3. 后端开发 - 负责服务端逻辑和API
4. 测试工程师 - 负责质量保证
5. DevOps工程师 - 负责部署和运维

工作职责：
1. 分析需求，拆解任务
2. 分配工作给合适的团队成员
3. 协调各角色之间的协作
4. 把控项目进度和质量
5. 解决技术难题和冲突

请确保团队高效协作，交付高质量的软件产品。""",
                output_format=OutputFormat(format_type="markdown"),
            ),
        ),
        AgentTemplate(
            id="tpl-dev-architect",
            name="系统架构师",
            description="负责系统设计和技术选型",
            category="specialist",
            icon="sitemap",
            is_official=True,
            definition=BuiltinAgentDefinition(
                name="系统架构师",
                description="设计可扩展、高可用的系统架构",
                model="gpt-4",
                temperature=0.4,
                system_prompt="""你是一位资深系统架构师，擅长设计复杂软件系统。

你的职责：
1. 分析业务需求，设计系统架构
2. 技术选型（编程语言、框架、数据库等）
3. 设计API接口和数据模型
4. 考虑性能、安全、可扩展性
5. 编写技术设计文档

设计原则：
- SOLID原则
- 微服务 vs 单体架构权衡
- 云原生设计
- 安全最佳实践

请提供清晰的架构图和详细的技术说明。""",
                output_format=OutputFormat(format_type="markdown"),
            ),
        ),
        AgentTemplate(
            id="tpl-dev-frontend",
            name="前端开发工程师",
            description="负责用户界面和交互开发",
            category="specialist",
            icon="desktop",
            is_official=True,
            definition=BuiltinAgentDefinition(
                name="前端开发工程师",
                description="构建优秀的用户界面和体验",
                model="gpt-4",
                temperature=0.4,
                system_prompt="""你是一位专业的前端开发工程师，精通现代前端技术栈。

技术专长：
- React/Vue/Angular
- TypeScript
- CSS/Tailwind/Styled Components
- 状态管理（Redux/Zustand/Pinia）
- 前端工程化（Vite/Webpack）

你的职责：
1. 实现用户界面设计
2. 开发交互功能
3. 优化性能和用户体验
4. 编写可维护的代码
5. 组件化和模块化开发

请确保代码质量、可访问性和跨浏览器兼容性。""",
                output_format=OutputFormat(format_type="markdown"),
            ),
        ),
        AgentTemplate(
            id="tpl-dev-backend",
            name="后端开发工程师",
            description="负责服务端逻辑和API开发",
            category="specialist",
            icon="server",
            is_official=True,
            definition=BuiltinAgentDefinition(
                name="后端开发工程师",
                description="构建稳定高效的后端服务",
                model="gpt-4",
                temperature=0.3,
                system_prompt="""你是一位资深后端开发工程师，擅长构建高性能服务。

技术专长：
- Python/Node.js/Go/Java
- RESTful API / GraphQL
- 数据库（PostgreSQL/MongoDB/Redis）
- 消息队列（RabbitMQ/Kafka）
- 微服务架构

你的职责：
1. 设计和实现API接口
2. 编写业务逻辑
3. 数据库设计和优化
4. 性能调优
5. 安全防护

请确保代码健壮、可测试、有良好的错误处理。""",
                output_format=OutputFormat(format_type="markdown"),
            ),
        ),
        AgentTemplate(
            id="tpl-dev-qa",
            name="测试工程师",
            description="负责软件质量保证",
            category="specialist",
            icon="bug",
            is_official=True,
            definition=BuiltinAgentDefinition(
                name="测试工程师",
                description="确保软件质量和可靠性",
                model="gpt-4",
                temperature=0.3,
                system_prompt="""你是一位专业的测试工程师，致力于软件质量保证。

测试专长：
- 单元测试/集成测试/E2E测试
- 测试框架（Jest/Pytest/Cypress）
- 性能测试/压力测试
- 安全测试
- 自动化测试

你的职责：
1. 制定测试计划和策略
2. 编写测试用例
3. 执行测试并记录结果
4. 报告和追踪缺陷
5. 持续改进测试流程

请确保全面覆盖，发现潜在问题。""",
                output_format=OutputFormat(format_type="markdown"),
            ),
        ),
    ]

    return templates


# ============== 工作流模板 ==============

class WorkflowTemplateAgent(BaseModel):
    """工作流模板中的 Agent 定义"""
    template_id: str  # 引用的 Agent 模板 ID
    name_override: Optional[str] = None  # 可选的名称覆盖
    parent_ref: Optional[str] = None  # 父节点引用（使用 ref_id）
    ref_id: str  # 本节点的引用 ID，用于建立父子关系


class WorkflowTemplate(BaseModel):
    """工作流模板定义"""
    id: str
    name: str
    description: str
    category: str
    icon: str
    is_official: bool = True
    agents: List[WorkflowTemplateAgent]  # 包含的 Agent 列表


def _get_builtin_workflow_templates() -> List[WorkflowTemplate]:
    """获取内置的工作流模板"""
    return [
        WorkflowTemplate(
            id="wf-tpl-travel-team",
            name="旅游规划团队",
            description="完整的旅游业务分析团队，包含6位专业顾问协作完成旅行规划",
            category="travel",
            icon="plane",
            is_official=True,
            agents=[
                WorkflowTemplateAgent(
                    ref_id="coordinator",
                    template_id="tpl-travel-coordinator",
                    parent_ref=None,
                ),
                WorkflowTemplateAgent(
                    ref_id="itinerary",
                    template_id="tpl-travel-itinerary",
                    parent_ref="coordinator",
                ),
                WorkflowTemplateAgent(
                    ref_id="hotel",
                    template_id="tpl-travel-hotel",
                    parent_ref="coordinator",
                ),
                WorkflowTemplateAgent(
                    ref_id="food",
                    template_id="tpl-travel-food",
                    parent_ref="coordinator",
                ),
                WorkflowTemplateAgent(
                    ref_id="budget",
                    template_id="tpl-travel-budget",
                    parent_ref="coordinator",
                ),
                WorkflowTemplateAgent(
                    ref_id="culture",
                    template_id="tpl-travel-culture",
                    parent_ref="coordinator",
                ),
            ],
        ),
        WorkflowTemplate(
            id="wf-tpl-dev-team",
            name="软件开发团队",
            description="完整的软件开发团队，包含技术负责人和各专业工程师",
            category="development",
            icon="laptop-code",
            is_official=True,
            agents=[
                WorkflowTemplateAgent(
                    ref_id="lead",
                    template_id="tpl-dev-lead",
                    parent_ref=None,
                ),
                WorkflowTemplateAgent(
                    ref_id="architect",
                    template_id="tpl-dev-architect",
                    parent_ref="lead",
                ),
                WorkflowTemplateAgent(
                    ref_id="frontend",
                    template_id="tpl-dev-frontend",
                    parent_ref="lead",
                ),
                WorkflowTemplateAgent(
                    ref_id="backend",
                    template_id="tpl-dev-backend",
                    parent_ref="lead",
                ),
                WorkflowTemplateAgent(
                    ref_id="qa",
                    template_id="tpl-dev-qa",
                    parent_ref="lead",
                ),
            ],
        ),
        WorkflowTemplate(
            id="wf-tpl-content-team",
            name="内容创作团队",
            description="内容策划、写作、审核的完整团队",
            category="content",
            icon="pen-fancy",
            is_official=True,
            agents=[
                WorkflowTemplateAgent(
                    ref_id="editor",
                    template_id="tpl-router",
                    name_override="内容主编",
                    parent_ref=None,
                ),
                WorkflowTemplateAgent(
                    ref_id="writer",
                    template_id="tpl-writer",
                    parent_ref="editor",
                ),
                WorkflowTemplateAgent(
                    ref_id="analyst",
                    template_id="tpl-analyst",
                    name_override="内容分析师",
                    parent_ref="editor",
                ),
            ],
        ),
    ]


# Import uuid for templates
from uuid import uuid4


# Create default app instance
app = create_app()


def run_server(host: str = "0.0.0.0", port: int = 8000):
    """Run the API server."""
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    run_server()
