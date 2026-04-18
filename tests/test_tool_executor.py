import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from src.adapters import builtin as builtin_module
from src.adapters.builtin import BuiltinAgentAdapter
from src import artifacts as artifacts_module
from src.core.agent_node import AgentNode
from src.core.context import ExecutionContext
from src.core.models import (
    AgentConfig,
    AgentResponse,
    AgentType,
    BuiltinAgentDefinition,
    ToolCall,
)
from src.execution import ExecutableTool, ToolExecutor
from src.governance import ApprovalStatus, ToolGovernanceSlice, get_approval_service
from src.governance import approval as approval_module
from src.governance.auto_revision import AutoSkillRevisionSlice
from src.plugins.registry import Tool as PluginTool
from src.storage import persistence as persistence_module


@pytest.mark.asyncio
async def test_tool_executor_blocks_unapproved_tool_and_records_audit():
    node = AgentNode(name="governed-agent", type=AgentType.BUILTIN)
    executor = ToolExecutor(node=node, slices=[ToolGovernanceSlice()])

    async def handler(params, context):
        return {"ok": True, "params": params, "ctx": id(context)}

    executor.register_tool(
        ExecutableTool(
            name="dangerous_tool",
            description="dangerous",
            parameters_schema={"type": "object", "properties": {}},
            handler=handler,
            source="builtin",
            approval_required=True,
        )
    )

    context = ExecutionContext()
    result = await executor.execute(
        tool_call=ToolCall(id="tc-1", name="dangerous_tool", arguments={}),
        context=context,
    )

    assert result.is_error is True
    assert "Approval required" in result.content
    assert context.metadata["tool_execution_audit"][0]["status"] == "blocked"
    assert context.metadata["tool_execution_audit"][0]["tool_name"] == "dangerous_tool"


@pytest.mark.asyncio
async def test_tool_executor_allows_approved_tool_and_preserves_context():
    node = AgentNode(name="approved-agent", type=AgentType.BUILTIN)
    executor = ToolExecutor(node=node, slices=[ToolGovernanceSlice()])
    observed = {}

    async def handler(params, context):
        observed["context"] = context
        return {"approved": True, "value": params["value"]}

    executor.register_tool(
        ExecutableTool(
            name="system_write",
            description="write",
            parameters_schema={"type": "object", "properties": {"value": {"type": "string"}}},
            handler=handler,
            source="system",
            approval_required=True,
            is_dangerous=True,
        )
    )

    context = ExecutionContext(metadata={"approved_tools": ["system_write"]})
    result = await executor.execute(
        tool_call=ToolCall(
            id="tc-2",
            name="system_write",
            arguments={"value": "ok"},
        ),
        context=context,
    )

    assert result.is_error is False
    assert json.loads(result.content) == {"approved": True, "value": "ok"}
    assert observed["context"] is context
    assert context.metadata["tool_execution_audit"][0]["status"] == "completed"


@pytest.mark.asyncio
async def test_builtin_adapter_uses_unified_executor_for_plugin_tools(monkeypatch):
    executed = {}

    async def plugin_handler(text: str):
        executed["text"] = text
        return {"echo": text}

    plugin_tool = PluginTool(
        name="plugin_echo",
        description="Echo from plugin",
        parameters_schema={
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
        handler=plugin_handler,
        source="skill",
    )

    class FakePluginRegistry:
        def get_tools_for_agent(self, agent_id: str):
            return [plugin_tool]

    monkeypatch.setattr(builtin_module, "get_plugin_registry", lambda: FakePluginRegistry())
    monkeypatch.setattr(BuiltinAgentAdapter, "_create_openai_client", lambda self: None)

    node = AgentNode(
        name="builtin-with-plugin",
        type=AgentType.BUILTIN,
        config=AgentConfig(
            builtin_definition=BuiltinAgentDefinition(
                name="builtin-with-plugin",
                use_global_llm=False,
            )
        ),
    )
    adapter = BuiltinAgentAdapter(node)
    await adapter.initialize()

    tool_names = {tool["function"]["name"] for tool in adapter._get_tools_for_api()}
    assert "plugin_echo" in tool_names

    response = AgentResponse(
        messages=[],
        tool_calls=[ToolCall(id="tc-3", name="plugin_echo", arguments={"text": "hello"})],
        response_id="resp-1",
    )
    handled = await adapter._handle_tool_calls(response, [], ExecutionContext())

    assert executed["text"] == "hello"
    assert handled.tool_results[0].is_error is False
    assert json.loads(handled.tool_results[0].content) == {"echo": "hello"}


@pytest.mark.asyncio
async def test_tool_executor_uses_persisted_approval_resolution(tmp_path, monkeypatch):
    monkeypatch.setenv("PROTON_STORAGE_TYPE", "file")
    monkeypatch.setenv("PROTON_STORAGE_PATH", str(tmp_path))
    persistence_module._storage_manager = None
    approval_module._approval_service = None

    node = AgentNode(name="persisted-approval-agent", type=AgentType.BUILTIN)
    executor = ToolExecutor(node=node, slices=[ToolGovernanceSlice()])

    async def handler(params, context):
        return {"approved": True, "value": params["value"], "ctx": context.execution_id}

    executor.register_tool(
        ExecutableTool(
            name="shell_like_tool",
            description="dangerous",
            parameters_schema={"type": "object", "properties": {"value": {"type": "string"}}},
            handler=handler,
            source="system",
            approval_required=True,
            is_dangerous=True,
        )
    )

    blocked_context = ExecutionContext(
        execution_id="exec-blocked",
        metadata={"workflow_id": "wf-approval"},
    )
    tool_call = ToolCall(
        id="tc-persisted-approval",
        name="shell_like_tool",
        arguments={"value": "ok"},
    )

    blocked_result = await executor.execute(tool_call=tool_call, context=blocked_context)

    assert blocked_result.is_error is True
    assert "approval_id=" in blocked_result.content
    assert blocked_result.metadata["approval_status"] == "pending"
    assert blocked_result.metadata["approval_id"]
    audit_entry = blocked_context.metadata["tool_execution_audit"][0]
    assert audit_entry["status"] == "blocked"
    assert "approval_id" in audit_entry

    approval_service = get_approval_service()
    approvals = await approval_service.list_approvals(status=ApprovalStatus.PENDING)
    assert len(approvals) == 1
    assert approvals[0].tool_call_id == tool_call.id

    await approval_service.resolve_approval(
        approvals[0].id,
        approved=True,
        actor="tester",
        comment="allow rerun",
    )

    approved_context = ExecutionContext(
        execution_id="exec-approved",
        metadata={"workflow_id": "wf-approval"},
    )
    approved_result = await executor.execute(tool_call=tool_call, context=approved_context)

    assert approved_result.is_error is False
    assert json.loads(approved_result.content) == {
        "approved": True,
        "value": "ok",
        "ctx": "exec-approved",
    }
    assert approved_result.metadata["approval_status"] == "approved"
    assert approved_result.metadata["approval_source"] == "persisted"
    assert approved_result.metadata["approval_id"] == approvals[0].id


@pytest.mark.asyncio
async def test_tool_executor_denies_unpaired_sender_by_policy():
    node = AgentNode(name="pairing-policy-agent", type=AgentType.BUILTIN)
    executor = ToolExecutor(node=node, slices=[ToolGovernanceSlice()])

    async def handler(params, context):
        _ = params, context
        return {"ok": True}

    executor.register_tool(
        ExecutableTool(
            name="shell_exec",
            description="execute shell",
            parameters_schema={"type": "object", "properties": {"command": {"type": "string"}}},
            handler=handler,
            source="system",
            approval_required=False,
            is_dangerous=True,
        )
    )

    context = ExecutionContext(
        metadata={
            "approval_policy": {
                "dm_policy": "pairing",
                "sender_paired": False,
            }
        }
    )
    result = await executor.execute(
        tool_call=ToolCall(id="tc-unpaired", name="shell_exec", arguments={"command": "ls"}),
        context=context,
    )

    assert result.is_error is True
    assert "Denied by policy" in result.content
    assert result.metadata["approval_status"] == "denied"
    assert result.metadata["reason"] == "dm_pairing_required"
    assert context.metadata["tool_execution_audit"][0]["status"] == "denied"


@pytest.mark.asyncio
async def test_tool_executor_requires_approval_for_command_pattern_policy():
    node = AgentNode(name="pattern-policy-agent", type=AgentType.BUILTIN)
    executor = ToolExecutor(node=node, slices=[ToolGovernanceSlice(persist_approval_requests=False)])

    async def handler(params, context):
        _ = context
        return {"ran": params["command"]}

    executor.register_tool(
        ExecutableTool(
            name="shell_exec",
            description="execute shell",
            parameters_schema={"type": "object", "properties": {"command": {"type": "string"}}},
            handler=handler,
            source="system",
            approval_required=False,
            is_dangerous=False,
        )
    )

    context = ExecutionContext(
        metadata={
            "approval_policy": {
                "require_approval_command_patterns": ["*rm -rf*"],
            }
        }
    )
    result = await executor.execute(
        tool_call=ToolCall(
            id="tc-command-pattern",
            name="shell_exec",
            arguments={"command": "rm -rf /tmp/demo"},
        ),
        context=context,
    )

    assert result.is_error is True
    assert "Approval required" in result.content
    assert result.metadata["approval_status"] == "pending"
    assert result.metadata["reason"] == "command_requires_approval_by_policy"


@pytest.mark.asyncio
async def test_auto_skill_revision_slice_triggers_on_fixable_skill_error():
    triggered = {}

    class _FakeCandidate:
        id = "cand-revision-1"

    class _FakeFactory:
        async def list_candidates(self):
            return []

        async def create_error_driven_revision_candidate(self, **kwargs):
            triggered["payload"] = kwargs
            return _FakeCandidate()

    artifacts_module.get_artifact_factory_service = lambda: _FakeFactory()

    node = AgentNode(name="auto-revision-agent", type=AgentType.BUILTIN)
    executor = ToolExecutor(node=node, slices=[AutoSkillRevisionSlice(enabled=True)])

    async def skill_handler(params, context):
        _ = params, context
        return {"error": "TypeError: bad input"}

    executor.register_tool(
        ExecutableTool(
            name="auto_skill_tool",
            description="skill with fixable error",
            parameters_schema={"type": "object", "properties": {}},
            handler=skill_handler,
            source="skill",
            metadata={"module": "skills.skill-abc.skill"},
        )
    )

    context = ExecutionContext(metadata={"user_id": "u1", "session_id": "s1"})
    result = await executor.execute(
        tool_call=ToolCall(id="tc-auto-fix-1", name="auto_skill_tool", arguments={}),
        context=context,
    )

    assert result.metadata.get("auto_revision_triggered") is True
    assert result.metadata.get("auto_revision_candidate_id") == "cand-revision-1"
    assert triggered["payload"]["tool_name"] == "auto_skill_tool"
    assert triggered["payload"]["error_type"] == "typeerror"


@pytest.mark.asyncio
async def test_auto_skill_revision_slice_ignores_non_fixable_errors():
    called = {"count": 0}

    class _FakeFactory:
        async def list_candidates(self):
            return []

        async def create_error_driven_revision_candidate(self, **kwargs):
            _ = kwargs
            called["count"] += 1
            class _C:
                id = "cand"
            return _C()

    artifacts_module.get_artifact_factory_service = lambda: _FakeFactory()

    node = AgentNode(name="auto-revision-agent-2", type=AgentType.BUILTIN)
    executor = ToolExecutor(node=node, slices=[AutoSkillRevisionSlice(enabled=True)])

    async def skill_handler(params, context):
        _ = params, context
        return {"error": "NetworkError: dependency timeout"}

    executor.register_tool(
        ExecutableTool(
            name="auto_skill_tool_2",
            description="skill with non-fixable error",
            parameters_schema={"type": "object", "properties": {}},
            handler=skill_handler,
            source="skill",
            metadata={"module": "skills.skill-def.skill"},
        )
    )

    context = ExecutionContext(metadata={"user_id": "u2", "session_id": "s2"})
    result = await executor.execute(
        tool_call=ToolCall(id="tc-auto-fix-2", name="auto_skill_tool_2", arguments={}),
        context=context,
    )

    assert result.metadata.get("auto_revision_triggered") is not True
    assert called["count"] == 0


@pytest.mark.asyncio
async def test_auto_skill_revision_slice_auto_grayscale_and_notice():
    called = {"approved": 0, "rollout": 0}

    class _Candidate:
        id = "cand-auto-r2"

    class _FakeFactory:
        async def list_candidates(self):
            return []

        async def create_error_driven_revision_candidate(self, **kwargs):
            _ = kwargs
            return _Candidate()

        async def approve_and_materialize(self, candidate_id: str, approver: str):
            _ = candidate_id, approver
            called["approved"] += 1
            return _Candidate()

        async def transition_rollout_status(self, **kwargs):
            _ = kwargs
            called["rollout"] += 1
            return _Candidate()

    artifacts_module.get_artifact_factory_service = lambda: _FakeFactory()

    node = AgentNode(name="auto-revision-agent-3", type=AgentType.BUILTIN)
    executor = ToolExecutor(
        node=node,
        slices=[AutoSkillRevisionSlice(enabled=True, auto_grayscale=True)],
    )

    async def skill_handler(params, context):
        _ = params, context
        return {"error": "SyntaxError: invalid syntax"}

    executor.register_tool(
        ExecutableTool(
            name="auto_skill_tool_3",
            description="skill with syntax error",
            parameters_schema={"type": "object", "properties": {}},
            handler=skill_handler,
            source="skill",
            metadata={"module": "skills.skill-ghi.skill"},
        )
    )

    context = ExecutionContext(metadata={"user_id": "u3", "session_id": "s3"})
    result = await executor.execute(
        tool_call=ToolCall(id="tc-auto-fix-3", name="auto_skill_tool_3", arguments={}),
        context=context,
    )

    assert result.metadata.get("auto_revision_triggered") is True
    assert result.metadata.get("auto_revision_rollout_status") == "grayscale"
    assert called["approved"] == 1
    assert called["rollout"] == 1
    notices = context.metadata.get("auto_revision_notifications")
    assert isinstance(notices, list) and notices
    assert notices[-1]["type"] == "auto_skill_revised"
