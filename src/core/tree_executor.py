"""
Tree-based executor for orchestrating agent hierarchies.

Handles:
- Executing agents in tree structure
- Different routing strategies
- Result aggregation
- Error handling and recovery
"""

import asyncio
import logging
from typing import Any, AsyncIterator, Callable, Dict, List, Optional
from uuid import uuid4

from .models import (
    AgentResponse,
    AgentResponseUpdate,
    ChatMessage,
    MessageRole,
    RoutingStrategy,
    ErrorHandlingStrategy,
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

    This is the core orchestration engine that:
    1. Traverses the agent tree
    2. Invokes agents based on routing strategy
    3. Manages context and state
    4. Aggregates results
    5. Handles errors
    """

    def __init__(
        self,
        tree: AgentTree,
        adapter_factory: Optional[Callable[[AgentNode], Any]] = None,
    ):
        """
        Initialize the tree executor.

        Args:
            tree: The agent tree to execute
            adapter_factory: Factory function to create adapters for agents
        """
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
        """Create an adapter for an agent node."""
        if self.adapter_factory:
            adapter = self.adapter_factory(node)
            if asyncio.iscoroutine(adapter):
                adapter = await adapter
            return adapter
        return None

    async def run(
        self,
        input_message: str,
        context: Optional[ExecutionContext] = None,
        start_node_id: Optional[str] = None,
    ) -> AgentResponse:
        """
        Execute the agent tree with the given input.

        Args:
            input_message: The user's input message
            context: Optional execution context (created if not provided)
            start_node_id: Optional starting node (defaults to root)

        Returns:
            AgentResponse with the final result
        """
        await self.initialize()

        # Create context if not provided
        if context is None:
            context = ExecutionContext(
                execution_id=str(uuid4()),
                max_depth=self.tree.get_max_depth() + 5,  # Buffer for safety
            )

        # Add input message to context
        context.add_message(ChatMessage(
            role=MessageRole.USER,
            content=input_message,
        ))

        # Get starting node
        start_node = None
        if start_node_id:
            start_node = self.tree.get_node(start_node_id)
        if not start_node:
            start_node = self.tree.get_root()

        if not start_node:
            raise WorkflowExecutionError(
                workflow_id=context.execution_id,
                message="No root node found in tree",
                errors=[],
            )

        # Execute from start node
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
        """
        Execute the agent tree with streaming output.

        Yields AgentResponseUpdate objects as execution progresses.
        """
        await self.initialize()

        # Create context
        if context is None:
            context = ExecutionContext(
                execution_id=str(uuid4()),
                max_depth=self.tree.get_max_depth() + 5,
            )

        context.add_message(ChatMessage(
            role=MessageRole.USER,
            content=input_message,
        ))

        # Get starting node
        start_node = None
        if start_node_id:
            start_node = self.tree.get_node(start_node_id)
        if not start_node:
            start_node = self.tree.get_root()

        if not start_node:
            yield AgentResponseUpdate(
                delta_content="Error: No root node found",
                is_complete=True,
            )
            return

        # Execute with streaming
        async for update in self._execute_node_stream(start_node, context):
            yield update

    async def _execute_node(
        self,
        node: AgentNode,
        context: ExecutionContext,
    ) -> AgentResponse:
        """
        Execute a single node in the tree.

        This method:
        1. Creates a child context
        2. Invokes the node's agent
        3. Routes to children based on strategy
        4. Aggregates results
        """
        if not node.enabled:
            return AgentResponse(
                messages=[],
                response_id=str(uuid4()),
                metadata={"skipped": True, "reason": "disabled"},
            )

        # Create child context for this node
        try:
            child_context = context.create_child_context(
                agent_id=node.id,
                layer_timeout=node.timeout,
            )
        except (CycleDetectedError, MaxDepthExceededError) as e:
            context.record_error(node.id, e, recoverable=False)
            if context.error_strategy == ErrorHandlingStrategy.FAIL_FAST:
                raise AgentExecutionError(node.id, str(e), e)
            return AgentResponse(
                messages=[],
                response_id=str(uuid4()),
                metadata={"error": str(e)},
            )

        logger.info(f"Executing node {node.name} ({node.id}) at depth {child_context.call_chain.depth}")

        # Execute this agent
        agent_response = await self._invoke_agent(node, child_context)

        # Store output
        child_context.set_agent_output(node.id, agent_response)

        # Add agent's response to context
        child_context.add_messages(agent_response.messages)

        # If this is a leaf node, return the response
        if node.is_leaf:
            return agent_response

        # Otherwise, route to children based on strategy
        children_responses = await self._route_to_children(
            node, child_context, agent_response
        )

        # Aggregate results
        return self._aggregate_responses(
            node, agent_response, children_responses, child_context
        )

    async def _execute_node_stream(
        self,
        node: AgentNode,
        context: ExecutionContext,
    ) -> AsyncIterator[AgentResponseUpdate]:
        """Execute a node with streaming output."""
        if not node.enabled:
            yield AgentResponseUpdate(
                delta_content="",
                is_complete=True,
                metadata={"skipped": True},
            )
            return

        try:
            child_context = context.create_child_context(
                agent_id=node.id,
                layer_timeout=node.timeout,
            )
        except (CycleDetectedError, MaxDepthExceededError) as e:
            yield AgentResponseUpdate(
                delta_content=f"Error: {e}",
                is_complete=True,
            )
            return

        # Stream from this agent
        collected_content = []
        async for update in self._invoke_agent_stream(node, child_context):
            yield update
            if update.delta_content:
                collected_content.append(update.delta_content)

        # Create response from collected content
        full_content = "".join(collected_content)
        agent_response = AgentResponse(
            messages=[ChatMessage(
                role=MessageRole.ASSISTANT,
                content=full_content,
                name=node.name,
            )],
            response_id=str(uuid4()),
        )
        child_context.set_agent_output(node.id, agent_response)
        child_context.add_messages(agent_response.messages)

        # If leaf node, we're done
        if node.is_leaf:
            return

        # Route to children
        children = self._get_routable_children(node, child_context, agent_response)
        for child in children:
            async for update in self._execute_node_stream(child, child_context):
                yield update

    async def _invoke_agent(
        self,
        node: AgentNode,
        context: ExecutionContext,
    ) -> AgentResponse:
        """Invoke a single agent."""
        if node.adapter is None:
            # No adapter - return empty response
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
                response = await node.adapter.run(
                    messages=messages,
                    context=context,
                )
                return response
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
        """Invoke a single agent with streaming."""
        if node.adapter is None:
            yield AgentResponseUpdate(
                delta_content=f"[Agent {node.name} has no adapter]",
                is_complete=True,
            )
            return

        messages = context.get_context_for_agent()

        try:
            async for update in node.adapter.run_stream(
                messages=messages,
                context=context,
            ):
                yield update
        except Exception as e:
            yield AgentResponseUpdate(
                delta_content=f"[Error: {e}]",
                is_complete=True,
            )

    async def _route_to_children(
        self,
        node: AgentNode,
        context: ExecutionContext,
        parent_response: AgentResponse,
    ) -> List[AgentResponse]:
        """Route execution to child agents based on strategy."""
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
            return await self._route_handoff(node, children, context, parent_response)

        elif strategy == RoutingStrategy.HIERARCHICAL:
            return await self._route_hierarchical(children, context, parent_response)

        elif strategy == RoutingStrategy.COORDINATOR:
            return await self._route_coordinator(node, children, context, parent_response)

        else:
            # Default to sequential
            return await self._route_sequential(children, context)

    def _get_routable_children(
        self,
        node: AgentNode,
        context: ExecutionContext,
        parent_response: AgentResponse,
    ) -> List[AgentNode]:
        """Get the list of children that should be routed to."""
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
        """Execute children sequentially, passing context forward."""
        responses = []
        for child in children:
            response = await self._execute_node(child, context)
            responses.append(response)
            # Update context with this child's response
            context.add_messages(response.messages)
        return responses

    async def _route_parallel(
        self,
        children: List[AgentNode],
        context: ExecutionContext,
    ) -> List[AgentResponse]:
        """Execute all children in parallel."""
        tasks = [
            self._execute_node(child, context)
            for child in children
        ]
        return await asyncio.gather(*tasks, return_exceptions=False)

    async def _route_conditional(
        self,
        node: AgentNode,
        children: List[AgentNode],
        context: ExecutionContext,
        parent_response: AgentResponse,
    ) -> List[AgentResponse]:
        """
        Route to specific child based on conditions.

        Evaluates routing_conditions to determine which child to invoke.
        """
        # Get the last message content for evaluation
        last_content = ""
        if parent_response.messages:
            last_content = parent_response.messages[-1].content

        # Simple condition matching
        # In production, use a proper expression evaluator
        target_child = None
        for condition, target_id in node.routing_conditions.items():
            # Simple keyword matching for demo
            # Format: "keyword: target_id"
            if "==" in condition:
                key, value = condition.split("==")
                key = key.strip()
                value = value.strip().strip("'\"")
                if value.lower() in last_content.lower():
                    target_child = self.tree.get_node(target_id)
                    break

        if target_child and target_child.enabled:
            response = await self._execute_node(target_child, context)
            return [response]

        # Default: execute first child if no condition matches
        if children:
            response = await self._execute_node(children[0], context)
            return [response]

        return []

    async def _route_handoff(
        self,
        node: AgentNode,
        children: List[AgentNode],
        context: ExecutionContext,
        parent_response: AgentResponse,
    ) -> List[AgentResponse]:
        """
        Handoff pattern: transfer control between agents.

        The parent agent decides which specialist to hand off to.
        """
        # Similar to conditional but allows multiple handoffs
        return await self._route_conditional(node, children, context, parent_response)

    async def _route_hierarchical(
        self,
        children: List[AgentNode],
        context: ExecutionContext,
        parent_response: AgentResponse,
    ) -> List[AgentResponse]:
        """
        Hierarchical decomposition: split task among children.

        Each child handles a sub-task, results are merged.
        """
        # Execute in parallel
        responses = await self._route_parallel(children, context)
        return responses

    async def _route_coordinator(
        self,
        node: AgentNode,
        children: List[AgentNode],
        context: ExecutionContext,
        parent_response: AgentResponse,
    ) -> List[AgentResponse]:
        """
        Coordinator pattern: Parent agent coordinates specialist children.

        Flow:
        1. Parent (coordinator) runs first - already done before this method
        2. All children (specialists) run in parallel
        3. Parent runs AGAIN to integrate all specialist outputs
        4. Return the integrated response

        This enables true multi-agent collaboration where the coordinator
        can see and integrate all specialist outputs.
        """
        logger.info(f"Coordinator pattern: {node.name} coordinating {len(children)} specialists")

        # Step 1: Run all specialists in parallel
        specialist_responses = await self._route_parallel(children, context)

        # Step 2: Build integration prompt with all specialist outputs
        integration_messages = []

        # Add a system message explaining the integration task
        integration_messages.append(ChatMessage(
            role=MessageRole.SYSTEM,
            content=(
                "Below are the outputs from your specialist team members. "
                "Please integrate their inputs into a comprehensive, coherent response. "
                "Make sure to:\n"
                "1. Synthesize all specialist insights\n"
                "2. Resolve any conflicts or inconsistencies\n"
                "3. Present a unified, well-structured final response\n"
                "4. If you have tools available (like file_write), use them to complete your task."
            ),
        ))

        # Add each specialist's output
        for i, (child, response) in enumerate(zip(children, specialist_responses)):
            if response.messages:
                specialist_output = "\n".join(m.content for m in response.messages if m.content)
                integration_messages.append(ChatMessage(
                    role=MessageRole.USER,
                    content=f"=== {child.name} 的输出 ===\n{specialist_output}",
                ))

        # Step 3: Invoke the coordinator again to integrate
        logger.info(f"Coordinator {node.name} integrating {len(specialist_responses)} specialist outputs")

        # Add integration messages to context
        for msg in integration_messages:
            context.add_message(msg)

        # Re-invoke the coordinator to integrate
        integration_response = await self._invoke_agent(node, context)

        # The integration response is the final output
        # We return both specialist responses (for history) and the integration response
        all_responses = specialist_responses + [integration_response]

        return all_responses

    def _aggregate_responses(
        self,
        node: AgentNode,
        parent_response: AgentResponse,
        children_responses: List[AgentResponse],
        context: ExecutionContext,
    ) -> AgentResponse:
        """
        Aggregate responses from parent and children.

        Different strategies may aggregate differently.
        """
        all_messages = list(parent_response.messages)
        all_tool_calls = list(parent_response.tool_calls)
        all_tool_results = list(parent_response.tool_results)

        for response in children_responses:
            all_messages.extend(response.messages)
            all_tool_calls.extend(response.tool_calls)
            all_tool_results.extend(response.tool_results)

        # For hierarchical, we might want to summarize
        if node.routing_strategy == RoutingStrategy.HIERARCHICAL:
            # Could add a summary message here
            pass

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


class WorkflowBuilder:
    """
    Fluent builder for creating agent tree workflows.

    Example:
        workflow = (
            WorkflowBuilder()
            .add_agent("router", AgentNode(...))
            .add_agent("specialist1", AgentNode(...), parent="router")
            .add_agent("specialist2", AgentNode(...), parent="router")
            .set_root("router")
            .build()
        )
    """

    def __init__(self):
        self._tree = AgentTree()
        self._adapter_factory = None

    def add_agent(
        self,
        node: AgentNode,
        parent_id: Optional[str] = None,
    ) -> "WorkflowBuilder":
        """Add an agent to the workflow."""
        if parent_id:
            node.parent_id = parent_id
        self._tree.add_node(node)
        return self

    def set_root(self, node_id: str) -> "WorkflowBuilder":
        """Set the root node of the workflow."""
        self._tree.root_id = node_id
        return self

    def set_adapter_factory(
        self,
        factory: Callable[[AgentNode], Any],
    ) -> "WorkflowBuilder":
        """Set the adapter factory."""
        self._adapter_factory = factory
        return self

    def add_routing_condition(
        self,
        node_id: str,
        condition: str,
        target_id: str,
    ) -> "WorkflowBuilder":
        """Add a routing condition to a node."""
        node = self._tree.get_node(node_id)
        if node:
            node.set_routing_condition(condition, target_id)
        return self

    def build(self) -> TreeExecutor:
        """Build and return the TreeExecutor."""
        errors = self._tree.validate()
        if errors:
            raise ValueError(f"Invalid tree structure: {errors}")

        return TreeExecutor(
            tree=self._tree,
            adapter_factory=self._adapter_factory,
        )
