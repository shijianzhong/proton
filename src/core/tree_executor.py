"""
Tree-based executor for orchestrating agent hierarchies.

Handles:
- Executing agents in tree structure
- Different routing strategies (including INTENT)
- Result aggregation
- Error handling and recovery
"""

import asyncio
import copy
import json
import logging
import os
import re
import time
from typing import Any, AsyncIterator, Callable, Dict, List, Optional
from uuid import uuid4

from .models import (
    AgentResponse,
    AgentResponseUpdate,
    ChatMessage,
    MessageRole,
    RoutingStrategy,
    ErrorHandlingStrategy,
    ExecutionEvent,
    ExecutionEventType,
    IntentUnderstandingResult,
    WorkflowDispatchPlan,
)
from .agent_node import AgentNode, AgentTree
from .context import (
    ExecutionContext,
    CallChain,
    CycleDetectedError,
    MaxDepthExceededError,
    AgentExecutionError,
    WorkflowExecutionError,
)

logger = logging.getLogger(__name__)


class TreeExecutor:
    """
    Executes agent trees with support for various routing strategies.

    Routing strategies available:
    - sequential   : children run one by one, context passes forward
    - parallel     : all children run concurrently
    - conditional  : keyword/regex match decides which child to run
    - handoff      : like conditional, for explicit delegation
    - hierarchical : parallel run then aggregate
    - coordinator  : parent → children → parent integrates
    - intent       : LLM understands input, selects + rewrites queries for children
    """

    def __init__(
        self,
        tree: AgentTree,
        adapter_factory: Optional[Callable[[AgentNode], Any]] = None,
    ):
        self.tree = tree
        self.adapter_factory = adapter_factory
        self._initialized = False

    async def initialize(self) -> None:
        """Initialize all agents in the tree."""
        if self._initialized:
            return

        if self.adapter_factory:
            for node in self.tree:
                if node.enabled and node.adapter is None:
                    try:
                        node.adapter = await self._create_adapter(node)
                    except Exception as e:
                        logger.error(f"Failed to create adapter for {node.id}: {e}")
                        raise

        self._initialized = True

    async def _create_adapter(self, node: AgentNode) -> Any:
        if self.adapter_factory:
            adapter = self.adapter_factory(node)
            if asyncio.iscoroutine(adapter):
                adapter = await adapter
            return adapter
        return None

    # ------------------------------------------------------------------ #
    #  Public run methods                                                  #
    # ------------------------------------------------------------------ #

    async def run(
        self,
        input_message: str,
        context: Optional[ExecutionContext] = None,
        start_node_id: Optional[str] = None,
    ) -> AgentResponse:
        await self.initialize()

        if context is None:
            context = ExecutionContext(
                execution_id=str(uuid4()),
                max_depth=self.tree.get_max_depth() + 5,
            )

        context.add_message(ChatMessage(role=MessageRole.USER, content=input_message))

        start_node = (
            self.tree.get_node(start_node_id) if start_node_id else None
        ) or self.tree.get_root()

        if not start_node:
            raise WorkflowExecutionError(
                workflow_id=context.execution_id,
                message="No root node found in tree",
                errors=[],
            )

        try:
            return await self._execute_node(start_node, context)
        except Exception as e:
            if context.errors:
                raise WorkflowExecutionError(
                    workflow_id=context.execution_id,
                    message=str(e),
                    errors=context.errors,
                )
            raise

    async def run_stream(
        self,
        input_message: str,
        context: Optional[ExecutionContext] = None,
        start_node_id: Optional[str] = None,
    ) -> AsyncIterator[AgentResponseUpdate]:
        await self.initialize()

        if context is None:
            context = ExecutionContext(
                execution_id=str(uuid4()),
                max_depth=self.tree.get_max_depth() + 5,
            )

        context.add_message(ChatMessage(role=MessageRole.USER, content=input_message))

        start_node = (
            self.tree.get_node(start_node_id) if start_node_id else None
        ) or self.tree.get_root()

        if not start_node:
            yield AgentResponseUpdate(delta_content="Error: No root node found", is_complete=True)
            return

        async for update in self._execute_node_stream(start_node, context):
            yield update

    async def run_stream_with_events(
        self,
        input_message: str,
        workflow_id: str,
        execution_id: str,
        context: Optional[ExecutionContext] = None,
        start_node_id: Optional[str] = None,
    ) -> AsyncIterator[ExecutionEvent]:
        await self.initialize()

        yield ExecutionEvent(
            event_type=ExecutionEventType.WORKFLOW_START,
            timestamp=time.time(),
            workflow_id=workflow_id,
            execution_id=execution_id,
            metadata={"input_message": input_message},
        )

        start_time = time.time()

        if context is None:
            context = ExecutionContext(
                execution_id=execution_id,
                max_depth=self.tree.get_max_depth() + 5,
            )

        context.add_message(ChatMessage(role=MessageRole.USER, content=input_message))

        start_node = (
            self.tree.get_node(start_node_id) if start_node_id else None
        ) or self.tree.get_root()

        if not start_node:
            yield ExecutionEvent(
                event_type=ExecutionEventType.WORKFLOW_ERROR,
                timestamp=time.time(),
                workflow_id=workflow_id,
                execution_id=execution_id,
                error="No root node found in tree",
            )
            return

        try:
            async for event in self._execute_node_with_events(
                start_node, context, workflow_id, execution_id, depth=0
            ):
                yield event

            duration_ms = (time.time() - start_time) * 1000
            yield ExecutionEvent(
                event_type=ExecutionEventType.WORKFLOW_COMPLETE,
                timestamp=time.time(),
                workflow_id=workflow_id,
                execution_id=execution_id,
                duration_ms=duration_ms,
                status="completed",
            )

        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000
            yield ExecutionEvent(
                event_type=ExecutionEventType.WORKFLOW_ERROR,
                timestamp=time.time(),
                workflow_id=workflow_id,
                execution_id=execution_id,
                error=str(e),
                duration_ms=duration_ms,
            )

    # ------------------------------------------------------------------ #
    #  Core node execution                                                 #
    # ------------------------------------------------------------------ #

    async def _execute_node(
        self,
        node: AgentNode,
        context: ExecutionContext,
    ) -> AgentResponse:
        if not node.enabled:
            return AgentResponse(
                messages=[],
                response_id=str(uuid4()),
                metadata={"skipped": True, "reason": "disabled"},
            )

        try:
            child_context = context.create_child_context(
                agent_id=node.id,
                layer_timeout=node.timeout,
            )
        except (CycleDetectedError, MaxDepthExceededError) as e:
            context.record_error(node.id, e, recoverable=False)
            if context.error_strategy == ErrorHandlingStrategy.FAIL_FAST:
                raise AgentExecutionError(node.id, str(e), e)
            return AgentResponse(messages=[], response_id=str(uuid4()), metadata={"error": str(e)})

        logger.info(f"Executing node {node.name} ({node.id}) depth={child_context.call_chain.depth}")

        agent_response = await self._invoke_agent(node, child_context)
        child_context.set_agent_output(node.id, agent_response)
        child_context.add_messages(agent_response.messages)

        if node.is_leaf:
            return agent_response

        children_responses = await self._route_to_children(node, child_context, agent_response)
        return self._aggregate_responses(node, agent_response, children_responses, child_context)

    async def _execute_node_stream(
        self,
        node: AgentNode,
        context: ExecutionContext,
    ) -> AsyncIterator[AgentResponseUpdate]:
        if not node.enabled:
            yield AgentResponseUpdate(delta_content="", is_complete=True, metadata={"skipped": True})
            return

        try:
            child_context = context.create_child_context(
                agent_id=node.id, layer_timeout=node.timeout,
            )
        except (CycleDetectedError, MaxDepthExceededError) as e:
            yield AgentResponseUpdate(delta_content=f"Error: {e}", is_complete=True)
            return

        collected_content = []
        async for update in self._invoke_agent_stream(node, child_context):
            yield update
            if update.delta_content:
                collected_content.append(update.delta_content)

        full_content = "".join(collected_content)
        agent_response = AgentResponse(
            messages=[ChatMessage(role=MessageRole.ASSISTANT, content=full_content, name=node.name)],
            response_id=str(uuid4()),
        )
        child_context.set_agent_output(node.id, agent_response)
        child_context.add_messages(agent_response.messages)

        if node.is_leaf:
            return

        children = self._get_routable_children(node, child_context, agent_response)
        for child in children:
            async for update in self._execute_node_stream(child, child_context):
                yield update

    async def _execute_node_with_events(
        self,
        node: AgentNode,
        context: ExecutionContext,
        workflow_id: str,
        execution_id: str,
        depth: int = 0,
    ) -> AsyncIterator[ExecutionEvent]:
        if not node.enabled:
            return

        node_start_time = time.time()

        yield ExecutionEvent(
            event_type=ExecutionEventType.NODE_START,
            timestamp=time.time(),
            workflow_id=workflow_id,
            execution_id=execution_id,
            node_id=node.id,
            node_name=node.name,
            depth=depth,
            status="running",
        )

        try:
            child_context = context.create_child_context(
                agent_id=node.id, layer_timeout=node.timeout,
            )
        except (CycleDetectedError, MaxDepthExceededError) as e:
            yield ExecutionEvent(
                event_type=ExecutionEventType.NODE_ERROR,
                timestamp=time.time(),
                workflow_id=workflow_id,
                execution_id=execution_id,
                node_id=node.id,
                node_name=node.name,
                depth=depth,
                error=str(e),
            )
            return

        collected_content = []
        tool_calls = []
        tool_results = []

        try:
            async for update in self._invoke_agent_stream(node, child_context):
                if update.delta_content:
                    collected_content.append(update.delta_content)
                    yield ExecutionEvent(
                        event_type=ExecutionEventType.NODE_THINKING,
                        timestamp=time.time(),
                        workflow_id=workflow_id,
                        execution_id=execution_id,
                        node_id=node.id,
                        node_name=node.name,
                        depth=depth,
                        delta_content=update.delta_content,
                    )
                if update.tool_call:
                    tool_calls.append(update.tool_call)
                    yield ExecutionEvent(
                        event_type=ExecutionEventType.NODE_TOOL_CALL,
                        timestamp=time.time(),
                        workflow_id=workflow_id,
                        execution_id=execution_id,
                        node_id=node.id,
                        node_name=node.name,
                        depth=depth,
                        tool_call=update.tool_call,
                    )
                if update.metadata and "tool_result" in update.metadata:
                    from .models import ToolResult
                    tr_data = update.metadata["tool_result"]
                    tr = ToolResult(
                        tool_call_id=tr_data["tool_call_id"],
                        content=tr_data["content"],
                        is_error=tr_data.get("is_error", False),
                        metadata=tr_data.get("metadata", {}),
                    )
                    tool_results.append(tr)
                    approval_status = tr.metadata.get("approval_status")
                    if approval_status == "pending":
                        yield ExecutionEvent(
                            event_type=ExecutionEventType.APPROVAL_REQUIRED,
                            timestamp=time.time(),
                            workflow_id=workflow_id,
                            execution_id=execution_id,
                            node_id=node.id,
                            node_name=node.name,
                            depth=depth,
                            tool_result=tr,
                            metadata=tr.metadata,
                        )
                    elif approval_status in {"approved", "denied"}:
                        yield ExecutionEvent(
                            event_type=ExecutionEventType.APPROVAL_RESOLVED,
                            timestamp=time.time(),
                            workflow_id=workflow_id,
                            execution_id=execution_id,
                            node_id=node.id,
                            node_name=node.name,
                            depth=depth,
                            tool_result=tr,
                            metadata=tr.metadata,
                        )
                    yield ExecutionEvent(
                        event_type=ExecutionEventType.NODE_TOOL_RESULT,
                        timestamp=time.time(),
                        workflow_id=workflow_id,
                        execution_id=execution_id,
                        node_id=node.id,
                        node_name=node.name,
                        depth=depth,
                        tool_result=tr,
                    )
        except Exception as e:
            yield ExecutionEvent(
                event_type=ExecutionEventType.NODE_ERROR,
                timestamp=time.time(),
                workflow_id=workflow_id,
                execution_id=execution_id,
                node_id=node.id,
                node_name=node.name,
                depth=depth,
                error=str(e),
            )
            return

        full_content = "".join(collected_content)
        agent_response = AgentResponse(
            messages=[ChatMessage(role=MessageRole.ASSISTANT, content=full_content, name=node.name)],
            tool_calls=tool_calls,
            tool_results=tool_results,
            response_id=str(uuid4()),
        )
        child_context.set_agent_output(node.id, agent_response)
        child_context.add_messages(agent_response.messages)

        duration_ms = (time.time() - node_start_time) * 1000
        yield ExecutionEvent(
            event_type=ExecutionEventType.NODE_COMPLETE,
            timestamp=time.time(),
            workflow_id=workflow_id,
            execution_id=execution_id,
            node_id=node.id,
            node_name=node.name,
            depth=depth,
            content=full_content,
            duration_ms=duration_ms,
            status="completed",
        )

        if node.is_leaf:
            return

        children = self._get_routable_children(node, child_context, agent_response)
        if not children:
            return

        # ---- Emit routing event ----
        yield ExecutionEvent(
            event_type=ExecutionEventType.ROUTING_START,
            timestamp=time.time(),
            workflow_id=workflow_id,
            execution_id=execution_id,
            node_id=node.id,
            node_name=node.name,
            depth=depth,
            routing_strategy=node.routing_strategy.value,
            target_nodes=[c.name for c in children],
        )

        # ---- INTENT routing: emit a dedicated event ----
        intent_result = None
        if node.routing_strategy == RoutingStrategy.INTENT:
            # Run intent routing; we'll get back a (possibly-reduced, sub-query-rewritten) child list
            intent_result, selected_children = await self._run_intent_routing(
                node, children, child_context, agent_response
            )
            yield ExecutionEvent(
                event_type=ExecutionEventType.INTENT_ROUTING,
                timestamp=time.time(),
                workflow_id=workflow_id,
                execution_id=execution_id,
                node_id=node.id,
                node_name=node.name,
                depth=depth,
                routing_strategy="intent",
                target_nodes=[c.name for c in selected_children],
                metadata={
                    "understood_intent": intent_result.understood_intent,
                    "clarification_needed": intent_result.clarification_needed,
                    "dispatch_count": len(intent_result.dispatch_plans),
                },
            )
            # Execute selected children with their sub-queries injected into context
            children_to_run = selected_children
            # Inject sub-queries into child_context messages
            self._inject_sub_queries(intent_result, child_context)
            await self._execute_intent_children_with_events(
                intent_result, children_to_run, child_context,
                workflow_id, execution_id, depth, self
            )
        else:
            children_to_run = children

        # ---- Execute children ----
        if node.routing_strategy == RoutingStrategy.PARALLEL:
            child_iterators = [
                self._execute_node_with_events(child, child_context, workflow_id, execution_id, depth + 1)
                for child in children_to_run
            ]
            for child_iter in child_iterators:
                async for event in child_iter:
                    yield event
        else:
            for child in children_to_run:
                async for event in self._execute_node_with_events(
                    child, child_context, workflow_id, execution_id, depth + 1
                ):
                    yield event

        # ---- COORDINATOR / INTENT synthesis ----
        if node.routing_strategy in (RoutingStrategy.COORDINATOR, RoutingStrategy.INTENT):
            cfg = (node.config.intent_routing_config if node.config else None)
            should_synthesise = (
                node.routing_strategy == RoutingStrategy.COORDINATOR
                or (cfg and cfg.synthesise_results)
            )
            if should_synthesise:
                integration_messages = [ChatMessage(
                    role=MessageRole.SYSTEM,
                    content=(
                        (cfg.synthesis_system_prompt if cfg and cfg.synthesis_system_prompt else None)
                        or (
                            "Below are the outputs from your specialist team members. "
                            "Please integrate their inputs into a comprehensive, coherent response."
                        )
                    ),
                )]
                for child in children_to_run:
                    child_output = child_context.get_agent_output(child.id)
                    if child_output and child_output.messages:
                        specialist_output = "\n".join(
                            m.content for m in child_output.messages if m.content
                        )
                        integration_messages.append(ChatMessage(
                            role=MessageRole.USER,
                            content=f"=== {child.name} 的输出 ===\n{specialist_output}",
                        ))
                for msg in integration_messages:
                    child_context.add_message(msg)

                yield ExecutionEvent(
                    event_type=ExecutionEventType.NODE_START,
                    timestamp=time.time(),
                    workflow_id=workflow_id,
                    execution_id=execution_id,
                    node_id=node.id,
                    node_name=f"{node.name} (Synthesis)",
                    depth=depth,
                    status="running",
                    metadata={"phase": "synthesis"},
                )
                integration_start = time.time()
                integration_content = []
                async for update in self._invoke_agent_stream(node, child_context):
                    if update.delta_content:
                        integration_content.append(update.delta_content)
                        yield ExecutionEvent(
                            event_type=ExecutionEventType.NODE_THINKING,
                            timestamp=time.time(),
                            workflow_id=workflow_id,
                            execution_id=execution_id,
                            node_id=node.id,
                            node_name=f"{node.name} (Synthesis)",
                            depth=depth,
                            delta_content=update.delta_content,
                        )
                    if update.tool_call:
                        yield ExecutionEvent(
                            event_type=ExecutionEventType.NODE_TOOL_CALL,
                            timestamp=time.time(),
                            workflow_id=workflow_id,
                            execution_id=execution_id,
                            node_id=node.id,
                            node_name=f"{node.name} (Synthesis)",
                            depth=depth,
                            tool_call=update.tool_call,
                        )

                yield ExecutionEvent(
                    event_type=ExecutionEventType.NODE_COMPLETE,
                    timestamp=time.time(),
                    workflow_id=workflow_id,
                    execution_id=execution_id,
                    node_id=node.id,
                    node_name=f"{node.name} (Synthesis)",
                    depth=depth,
                    content="".join(integration_content),
                    duration_ms=(time.time() - integration_start) * 1000,
                    status="completed",
                    metadata={"phase": "synthesis"},
                )

    # ------------------------------------------------------------------ #
    #  Agent invocation                                                    #
    # ------------------------------------------------------------------ #

    async def _invoke_agent(
        self,
        node: AgentNode,
        context: ExecutionContext,
    ) -> AgentResponse:
        if node.adapter is None:
            logger.warning(f"No adapter for node {node.id}")
            return AgentResponse(
                messages=[ChatMessage(
                    role=MessageRole.ASSISTANT,
                    content=f"[Agent {node.name} has no adapter configured]",
                    name=node.name,
                )],
                response_id=str(uuid4()),
            )

        messages = context.get_context_for_agent()
        try:
            async with context.timeout_scope(node.timeout):
                return await node.adapter.run(messages=messages, context=context)
        except asyncio.TimeoutError:
            context.record_error(
                node.id,
                TimeoutError(f"Agent {node.id} timed out after {node.timeout}s"),
                recoverable=True,
            )
            return AgentResponse(
                messages=[ChatMessage(
                    role=MessageRole.ASSISTANT,
                    content=f"[Agent {node.name} timed out]",
                    name=node.name,
                )],
                response_id=str(uuid4()),
                metadata={"timeout": True},
            )
        except Exception as e:
            context.record_error(node.id, e, recoverable=False)
            if context.error_strategy == ErrorHandlingStrategy.FAIL_FAST:
                raise AgentExecutionError(node.id, str(e), e)
            return AgentResponse(
                messages=[ChatMessage(
                    role=MessageRole.ASSISTANT,
                    content=f"[Agent {node.name} error: {e}]",
                    name=node.name,
                )],
                response_id=str(uuid4()),
                metadata={"error": str(e)},
            )

    async def _invoke_agent_stream(
        self,
        node: AgentNode,
        context: ExecutionContext,
    ) -> AsyncIterator[AgentResponseUpdate]:
        if node.adapter is None:
            yield AgentResponseUpdate(
                delta_content=f"[Agent {node.name} has no adapter]",
                is_complete=True,
            )
            return

        messages = context.get_context_for_agent()
        try:
            stream = node.adapter.run_stream(messages=messages, context=context)
            if asyncio.iscoroutine(stream):
                stream = await stream
            assert not asyncio.iscoroutine(stream)
            async for update in stream:
                yield update
        except Exception as e:
            yield AgentResponseUpdate(delta_content=f"[Error: {e}]", is_complete=True)

    # ------------------------------------------------------------------ #
    #  Routing dispatch                                                    #
    # ------------------------------------------------------------------ #

    async def _route_to_children(
        self,
        node: AgentNode,
        context: ExecutionContext,
        parent_response: AgentResponse,
    ) -> List[AgentResponse]:
        children = self._get_routable_children(node, context, parent_response)
        if not children:
            return []

        strategy = node.routing_strategy

        if strategy == RoutingStrategy.SEQUENTIAL:
            return await self._route_sequential(children, context)
        elif strategy == RoutingStrategy.PARALLEL:
            return await self._route_parallel(children, context)
        elif strategy == RoutingStrategy.CONDITIONAL:
            return await self._route_conditional(node, children, context, parent_response)
        elif strategy == RoutingStrategy.HANDOFF:
            return await self._route_conditional(node, children, context, parent_response)
        elif strategy == RoutingStrategy.HIERARCHICAL:
            return await self._route_parallel(children, context)
        elif strategy == RoutingStrategy.COORDINATOR:
            return await self._route_coordinator(node, children, context, parent_response)
        elif strategy == RoutingStrategy.INTENT:
            return await self._route_intent(node, children, context, parent_response)
        else:
            return await self._route_sequential(children, context)

    def _get_routable_children(
        self,
        node: AgentNode,
        context: ExecutionContext,
        parent_response: AgentResponse,
    ) -> List[AgentNode]:
        children = []
        for child_id in node.children:
            child = self.tree.get_node(child_id)
            if child and child.enabled:
                children.append(child)
        return children

    async def _route_sequential(
        self,
        children: List[AgentNode],
        context: ExecutionContext,
    ) -> List[AgentResponse]:
        responses = []
        for child in children:
            response = await self._execute_node(child, context)
            responses.append(response)
            context.add_messages(response.messages)
        return responses

    async def _route_parallel(
        self,
        children: List[AgentNode],
        context: ExecutionContext,
    ) -> List[AgentResponse]:
        isolated_contexts = []
        tasks = []
        for child in children:
            # Create a manual isolated context for parallel execution to avoid state corruption
            child_ctx = ExecutionContext(
                call_chain=context.call_chain,
                max_depth=context.max_depth,
                shared_state=copy.deepcopy(context.shared_state),
                agent_outputs=context.agent_outputs.copy(),
                messages=context.messages.copy(),
                compressed_context=context.compressed_context,
                max_context_tokens=context.max_context_tokens,
                total_timeout=context.total_timeout,
                layer_timeout=context.layer_timeout,
                remaining_timeout=context.remaining_timeout,
                error_strategy=context.error_strategy,
                errors=list(context.errors),
                warnings=list(context.warnings),
                execution_id=context.execution_id,
                parent_execution_id=context.execution_id,
                metadata=context.metadata.copy(),
            )
            isolated_contexts.append(child_ctx)
            tasks.append(self._execute_node(child, child_ctx))
            
        responses = await asyncio.gather(*tasks, return_exceptions=False)
        
        # Merge isolated contexts back into parent
        for child_ctx in isolated_contexts:
            context.merge_isolated_context(child_ctx)
            
        return responses

    async def _route_conditional(
        self,
        node: AgentNode,
        children: List[AgentNode],
        context: ExecutionContext,
        parent_response: AgentResponse,
    ) -> List[AgentResponse]:
        last_content = parent_response.messages[-1].content if parent_response.messages else ""
        target_child = None
        for condition, target_id in node.routing_conditions.items():
            if "==" in condition:
                _, value = condition.split("==")
                value = value.strip().strip("'\"")
                if value.lower() in last_content.lower():
                    target_child = self.tree.get_node(target_id)
                    break

        if target_child and target_child.enabled:
            return [await self._execute_node(target_child, context)]
        if children:
            return [await self._execute_node(children[0], context)]
        return []

    async def _route_coordinator(
        self,
        node: AgentNode,
        children: List[AgentNode],
        context: ExecutionContext,
        parent_response: AgentResponse,
    ) -> List[AgentResponse]:
        specialist_responses = await self._route_parallel(children, context)
        self._build_integration_context(node, children, specialist_responses, context)
        integration_response = await self._invoke_agent(node, context)
        return specialist_responses + [integration_response]

    # ------------------------------------------------------------------ #
    #  INTENT routing — the new strategy                                  #
    # ------------------------------------------------------------------ #

    async def _route_intent(
        self,
        node: AgentNode,
        children: List[AgentNode],
        context: ExecutionContext,
        parent_response: AgentResponse,
    ) -> List[AgentResponse]:
        """
        INTENT routing strategy.

        1. Use LLM to understand the current query and select which children to call,
           generating a per-child refined sub-query.
        2. Execute selected children (parallel within same priority, sequential across priorities).
        3. If synthesise_results=True (default), re-invoke this node to integrate outputs.
        """
        intent_result, selected_children = await self._run_intent_routing(
            node, children, context, parent_response
        )

        if not selected_children:
            logger.warning(f"[Intent] No children selected for node {node.name}, falling back to all")
            selected_children = children

        # Inject sub-queries as context messages
        self._inject_sub_queries(intent_result, context)

        # Execute by priority groups
        responses = await self._execute_by_priority(intent_result, selected_children, context)

        # Synthesise
        cfg = node.config.intent_routing_config if node.config else None
        if cfg is None or cfg.synthesise_results:
            self._build_integration_context(
                node, selected_children, responses, context,
                system_prompt=(cfg.synthesis_system_prompt if cfg else None),
            )
            integration_response = await self._invoke_agent(node, context)
            return responses + [integration_response]

        return responses

    async def _run_intent_routing(
        self,
        node: AgentNode,
        children: List[AgentNode],
        context: ExecutionContext,
        parent_response: AgentResponse,
    ):
        """
        Call IntentUnderstandingService for this node and return
        (IntentUnderstandingResult, list_of_selected_AgentNode).
        """
        from ..portal.intent import IntentUnderstandingService

        cfg = node.config.intent_routing_config if node.config else None
        llm_client = self._build_llm_client(node, cfg)

        model = None
        temperature = 0.2
        if cfg:
            model = cfg.model
            temperature = cfg.temperature

        if not model:
            try:
                from ..copilot import get_copilot_service

                global_cfg = get_copilot_service().get_internal_config()
                model = global_cfg.get("model")
            except Exception:
                model = None

        if not model:
            model = node.config.model if node.config else "gpt-4"

        intent_svc = IntentUnderstandingService(
            llm_client=llm_client,
            model=model,
            temperature=temperature,
        )

        # Build child descriptors
        child_descriptors = [
            {"id": c.id, "name": c.name, "description": c.description}
            for c in children
        ]

        # Get the current input from context
        user_query = ""
        for msg in reversed(context.messages):
            if msg.role == MessageRole.USER:
                user_query = msg.content
                break
        if not user_query and parent_response.messages:
            user_query = parent_response.messages[-1].content

        max_sel = cfg.max_children_selected if cfg else 0
        fallback = cfg.fallback_to_all if cfg else True

        intent_result = None
        try:
            intent_result = await intent_svc.understand(
                user_query=user_query,
                available_children=child_descriptors,
                conversation_history=[
                    {"role": m.role.value, "content": m.content}
                    for m in context.messages[-10:]
                ],
                max_selected=max_sel,
            )
        except Exception as e:
            logger.error(f"[Intent] routing LLM call failed for node {node.name}: {e}")
            if fallback:
                # Return trivial result dispatching to all children
                from ..core.models import IntentUnderstandingResult, WorkflowDispatchPlan
                intent_result = IntentUnderstandingResult(
                    original_query=user_query,
                    understood_intent=user_query,
                    dispatch_plans=[
                        WorkflowDispatchPlan(
                            workflow_id=c.id, workflow_name=c.name,
                            sub_query=user_query, reason="fallback", priority=0,
                        )
                        for c in children
                    ],
                )
            else:
                raise
        if intent_result is None:
            raise RuntimeError("Intent routing failed without fallback")

        # Map dispatch_plans back to AgentNode objects
        selected_ids = {p.workflow_id for p in intent_result.dispatch_plans}
        selected_children = [c for c in children if c.id in selected_ids]
        # Preserve original children if nothing selected
        if not selected_children and fallback:
            selected_children = children

        return intent_result, selected_children

    def _build_llm_client(self, node: AgentNode, cfg):
        """Build an AsyncOpenAI-compatible client for intent routing."""
        try:
            from openai import AsyncOpenAI
        except ImportError:
            raise RuntimeError("openai package required for INTENT routing. pip install openai")

        kwargs: Dict[str, Any] = {}

        api_key = None
        base_url = None

        if cfg:
            api_key = cfg.api_key
            base_url = cfg.base_url

        if not api_key and node.config and node.config.builtin_definition:
            api_key = node.config.builtin_definition.api_key
            base_url = base_url or node.config.builtin_definition.base_url

        if not api_key or not base_url:
            try:
                from ..copilot import get_copilot_service

                global_cfg = get_copilot_service().get_internal_config()
                if not api_key:
                    api_key = global_cfg.get("api_key")
                if not base_url and global_cfg.get("base_url"):
                    base_url = global_cfg.get("base_url")
            except Exception:
                pass

        if not api_key:
            api_key = os.environ.get("OPENAI_API_KEY")
        if not base_url:
            base_url = os.environ.get("OPENAI_BASE_URL")

        if api_key:
            kwargs["api_key"] = api_key
        if base_url:
            kwargs["base_url"] = base_url

        return AsyncOpenAI(**kwargs)

    async def _execute_by_priority(
        self,
        intent_result: IntentUnderstandingResult,
        selected_children: List[AgentNode],
        context: ExecutionContext,
    ) -> List[AgentResponse]:
        """Execute selected children respecting priority groups."""
        # Build priority → children map
        plan_by_id = {p.workflow_id: p for p in intent_result.dispatch_plans}
        priority_groups: Dict[int, List[AgentNode]] = {}
        for child in selected_children:
            plan = plan_by_id.get(child.id)
            priority = plan.priority if plan else 0
            priority_groups.setdefault(priority, []).append(child)

        all_responses = []
        for priority in sorted(priority_groups.keys()):
            group = priority_groups[priority]
            if len(group) == 1:
                resp = await self._execute_node(group[0], context)
                all_responses.append(resp)
                context.add_messages(resp.messages)
            else:
                # Same priority → parallel with isolated contexts
                isolated_contexts = []
                tasks = []
                for child in group:
                    child_ctx = ExecutionContext(
                        call_chain=context.call_chain,
                        max_depth=context.max_depth,
                        shared_state=copy.deepcopy(context.shared_state),
                        agent_outputs=context.agent_outputs.copy(),
                        messages=context.messages.copy(),
                        compressed_context=context.compressed_context,
                        max_context_tokens=context.max_context_tokens,
                        total_timeout=context.total_timeout,
                        layer_timeout=context.layer_timeout,
                        remaining_timeout=context.remaining_timeout,
                        error_strategy=context.error_strategy,
                        errors=list(context.errors),
                        warnings=list(context.warnings),
                        execution_id=context.execution_id,
                        parent_execution_id=context.execution_id,
                        metadata=context.metadata.copy(),
                    )
                    isolated_contexts.append(child_ctx)
                    tasks.append(self._execute_node(child, child_ctx))
                
                responses = await asyncio.gather(*tasks, return_exceptions=False)
                all_responses.extend(responses)
                
                # Merge isolated contexts and messages back into parent
                for child_ctx, resp in zip(isolated_contexts, responses):
                    context.merge_isolated_context(child_ctx)
                    context.add_messages(resp.messages)
        return all_responses

    def _inject_sub_queries(
        self,
        intent_result: IntentUnderstandingResult,
        context: ExecutionContext,
    ) -> None:
        """
        Insert the refined sub-queries into context as system messages so
        each child receives its tailored input when context.get_context_for_agent()
        is called.  We add a single system message summarising all sub-queries;
        individual children then receive it as part of their message history.
        """
        if not intent_result.dispatch_plans:
            return

        lines = [f"Intent understood: {intent_result.understood_intent}", ""]
        for plan in intent_result.dispatch_plans:
            lines.append(f"- [{plan.workflow_name}]: {plan.sub_query}")

        context.add_message(ChatMessage(
            role=MessageRole.SYSTEM,
            content="\n".join(lines),
            metadata={"intent_routing": True},
        ))

    def _build_integration_context(
        self,
        node: AgentNode,
        children: List[AgentNode],
        responses: List[AgentResponse],
        context: ExecutionContext,
        system_prompt: Optional[str] = None,
    ) -> None:
        """Add specialist outputs + integration instruction to context."""
        context.add_message(ChatMessage(
            role=MessageRole.SYSTEM,
            content=system_prompt or (
                "Below are the outputs from your specialist team members. "
                "Please integrate their inputs into a comprehensive, coherent response. "
                "Make sure to:\n"
                "1. Synthesize all specialist insights\n"
                "2. Resolve any conflicts or inconsistencies\n"
                "3. Present a unified, well-structured final response\n"
                "4. If you have tools available (like file_write), use them to complete your task."
            ),
        ))
        for child, response in zip(children, responses):
            if response.messages:
                specialist_output = "\n".join(m.content for m in response.messages if m.content)
                context.add_message(ChatMessage(
                    role=MessageRole.USER,
                    content=f"=== {child.name} 的输出 ===\n{specialist_output}",
                ))

    # ------------------------------------------------------------------ #
    #  Placeholder for events-path parallel intent execution              #
    # ------------------------------------------------------------------ #
    async def _execute_intent_children_with_events(
        self,
        intent_result,
        children: List[AgentNode],
        context: ExecutionContext,
        workflow_id: str,
        execution_id: str,
        depth: int,
        executor,
    ):
        """No-op: the events path handles this inline via sequential iteration."""
        pass

    # ------------------------------------------------------------------ #
    #  Aggregation                                                         #
    # ------------------------------------------------------------------ #

    def _aggregate_responses(
        self,
        node: AgentNode,
        parent_response: AgentResponse,
        children_responses: List[AgentResponse],
        context: ExecutionContext,
    ) -> AgentResponse:
        all_messages = list(parent_response.messages)
        all_tool_calls = list(parent_response.tool_calls)
        all_tool_results = list(parent_response.tool_results)

        for response in children_responses:
            all_messages.extend(response.messages)
            all_tool_calls.extend(response.tool_calls)
            all_tool_results.extend(response.tool_results)

        return AgentResponse(
            messages=all_messages,
            tool_calls=all_tool_calls,
            tool_results=all_tool_results,
            response_id=str(uuid4()),
            metadata={
                "aggregated_from": [r.response_id for r in children_responses],
                "parent_response_id": parent_response.response_id,
            },
        )


# ------------------------------------------------------------------ #
#  WorkflowBuilder                                                     #
# ------------------------------------------------------------------ #

class WorkflowBuilder:
    """Fluent builder for creating agent tree workflows."""

    def __init__(self):
        self._tree = AgentTree()
        self._adapter_factory = None

    def add_agent(self, node: AgentNode, parent_id: Optional[str] = None) -> "WorkflowBuilder":
        if parent_id:
            node.parent_id = parent_id
        self._tree.add_node(node)
        return self

    def set_root(self, node_id: str) -> "WorkflowBuilder":
        self._tree.root_id = node_id
        return self

    def set_adapter_factory(self, factory: Callable[[AgentNode], Any]) -> "WorkflowBuilder":
        self._adapter_factory = factory
        return self

    def add_routing_condition(self, node_id: str, condition: str, target_id: str) -> "WorkflowBuilder":
        node = self._tree.get_node(node_id)
        if node:
            node.set_routing_condition(condition, target_id)
        return self

    def build(self) -> TreeExecutor:
        errors = self._tree.validate()
        if errors:
            raise ValueError(f"Invalid tree structure: {errors}")
        return TreeExecutor(tree=self._tree, adapter_factory=self._adapter_factory)
