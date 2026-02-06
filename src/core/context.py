"""
Execution context and call chain management for tree-based agent orchestration.

Handles:
- Call chain tracking to prevent cycles
- Context compression for deep nesting
- Timeout management across layers
- Shared state between agents
"""

import time
import asyncio
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set
from contextlib import asynccontextmanager
import logging

from .models import ChatMessage, AgentResponse, ErrorHandlingStrategy

logger = logging.getLogger(__name__)


@dataclass
class CallChain:
    """
    Tracks the agent call chain to detect cycles and manage depth.

    Attributes:
        chain: List of agent IDs in call order [root, child1, child2, ...]
        workflow_ids: List of workflow IDs in the call chain (for workflow inter-calling)
        depth: Current nesting depth
        start_time: When execution started
        context_tokens: Estimated token count in context
    """
    chain: List[str] = field(default_factory=list)
    workflow_ids: List[str] = field(default_factory=list)  # Track workflow references
    depth: int = 0
    start_time: float = field(default_factory=time.time)
    context_tokens: int = 0
    _visited: Set[str] = field(default_factory=set)

    def push(self, agent_id: str) -> "CallChain":
        """
        Add an agent to the call chain.

        Returns a new CallChain with the agent added.
        """
        new_chain = CallChain(
            chain=self.chain + [agent_id],
            workflow_ids=self.workflow_ids.copy(),  # Copy workflow IDs
            depth=self.depth + 1,
            start_time=self.start_time,
            context_tokens=self.context_tokens,
            _visited=self._visited | {agent_id}
        )
        return new_chain

    def check_cycle(self, agent_id: str) -> bool:
        """
        Check if calling this agent would create a cycle.

        Returns True if the agent is already in the call chain.
        """
        return agent_id in self._visited

    def check_depth(self, max_depth: int) -> bool:
        """
        Check if we've exceeded the maximum depth.

        Returns True if current depth >= max_depth.
        """
        return self.depth >= max_depth

    def get_elapsed_time(self) -> float:
        """Get seconds elapsed since execution started."""
        return time.time() - self.start_time

    def get_path_string(self) -> str:
        """Get a string representation of the call path."""
        return " -> ".join(self.chain) if self.chain else "(root)"

    def get_workflow_ids(self) -> List[str]:
        """Get list of workflow IDs in the call chain."""
        return self.workflow_ids

    def add_workflow(self, workflow_id: str) -> None:
        """Add a workflow ID to the tracking list."""
        self.workflow_ids.append(workflow_id)

    def __str__(self) -> str:
        return f"CallChain(depth={self.depth}, path={self.get_path_string()})"


@dataclass
class ExecutionContext:
    """
    Execution context passed through the agent tree.

    Contains:
    - Call chain for cycle detection
    - Shared state between agents
    - Message history with compression
    - Timeout management
    - Error tracking
    """
    # Call tracking
    call_chain: CallChain = field(default_factory=CallChain)
    max_depth: int = 10

    # Shared state
    shared_state: Dict[str, Any] = field(default_factory=dict)
    agent_outputs: Dict[str, AgentResponse] = field(default_factory=dict)

    # Message history
    messages: List[ChatMessage] = field(default_factory=list)
    compressed_context: Optional[str] = None
    max_context_tokens: int = 32000

    # Timeout management
    total_timeout: float = 300.0  # 5 minutes default
    layer_timeout: float = 60.0   # 1 minute per layer default
    remaining_timeout: float = 300.0

    # Error handling
    error_strategy: ErrorHandlingStrategy = ErrorHandlingStrategy.FAIL_FAST
    errors: List[Dict[str, Any]] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    # Execution metadata
    execution_id: str = ""
    parent_execution_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def create_child_context(
        self,
        agent_id: str,
        layer_timeout: Optional[float] = None
    ) -> "ExecutionContext":
        """
        Create a child context for a sub-agent call.

        Args:
            agent_id: ID of the agent being called
            layer_timeout: Optional timeout override for this layer

        Returns:
            New ExecutionContext for the child agent

        Raises:
            CycleDetectedError: If calling this agent would create a cycle
            MaxDepthExceededError: If maximum depth would be exceeded
        """
        # Check for cycles
        if self.call_chain.check_cycle(agent_id):
            raise CycleDetectedError(
                f"Cycle detected: {agent_id} is already in call chain "
                f"{self.call_chain.get_path_string()}"
            )

        # Check depth
        if self.call_chain.check_depth(self.max_depth):
            raise MaxDepthExceededError(
                f"Maximum depth {self.max_depth} exceeded at "
                f"{self.call_chain.get_path_string()}"
            )

        # Calculate remaining timeout
        elapsed = self.call_chain.get_elapsed_time()
        new_remaining = max(0, self.total_timeout - elapsed)

        if new_remaining <= 0:
            raise TimeoutError(
                f"Total timeout {self.total_timeout}s exceeded after {elapsed:.1f}s"
            )

        # Create child context
        child = ExecutionContext(
            call_chain=self.call_chain.push(agent_id),
            max_depth=self.max_depth,
            shared_state=self.shared_state,  # Shared reference
            agent_outputs=self.agent_outputs,  # Shared reference
            messages=self.messages.copy(),  # Copy messages
            compressed_context=self.compressed_context,
            max_context_tokens=self.max_context_tokens,
            total_timeout=self.total_timeout,
            layer_timeout=layer_timeout or self.layer_timeout,
            remaining_timeout=new_remaining,
            error_strategy=self.error_strategy,
            errors=self.errors,  # Shared reference for error collection
            warnings=self.warnings,  # Shared reference
            execution_id=self.execution_id,
            parent_execution_id=self.execution_id,
            metadata=self.metadata.copy(),
        )

        return child

    def add_message(self, message: ChatMessage) -> None:
        """Add a message to the history."""
        self.messages.append(message)
        self._estimate_tokens()

    def add_messages(self, messages: List[ChatMessage]) -> None:
        """Add multiple messages to the history."""
        self.messages.extend(messages)
        self._estimate_tokens()

    def _estimate_tokens(self) -> None:
        """Estimate token count and compress if needed."""
        # Simple estimation: ~4 chars per token
        total_chars = sum(len(m.content) for m in self.messages)
        self.call_chain.context_tokens = total_chars // 4

        # Compress if exceeding limit
        if self.call_chain.context_tokens > self.max_context_tokens:
            self._compress_context()

    def _compress_context(self) -> None:
        """
        Compress context when it exceeds the token limit.

        Strategy:
        1. Keep system messages
        2. Keep last N user/assistant exchanges
        3. Summarize older messages
        """
        if len(self.messages) <= 4:
            return

        # Keep first message (often system) and last 3 exchanges
        keep_first = self.messages[:1]
        keep_last = self.messages[-6:]  # Last 3 exchanges

        # Summarize middle messages
        middle = self.messages[1:-6]
        if middle:
            summary = self._summarize_messages(middle)
            self.compressed_context = summary
            self.messages = keep_first + keep_last
            self.warnings.append(
                f"Context compressed: {len(middle)} messages summarized"
            )

    def _summarize_messages(self, messages: List[ChatMessage]) -> str:
        """Create a summary of messages for context compression."""
        # Simple summary - in production, use an LLM to summarize
        summary_parts = []
        for msg in messages:
            role = msg.role.value
            content = msg.content[:100] + "..." if len(msg.content) > 100 else msg.content
            summary_parts.append(f"[{role}]: {content}")

        return "\n".join(summary_parts)

    def get_context_for_agent(self) -> List[ChatMessage]:
        """
        Get the message context for an agent, including any compressed context.
        """
        if self.compressed_context:
            # Insert compressed context as a system message
            from .models import MessageRole
            compressed_msg = ChatMessage(
                role=MessageRole.SYSTEM,
                content=f"[Previous conversation summary]:\n{self.compressed_context}"
            )
            return [compressed_msg] + self.messages
        return self.messages

    def record_error(
        self,
        agent_id: str,
        error: Exception,
        recoverable: bool = False
    ) -> None:
        """Record an error that occurred during execution."""
        self.errors.append({
            "agent_id": agent_id,
            "error_type": type(error).__name__,
            "error_message": str(error),
            "call_path": self.call_chain.get_path_string(),
            "depth": self.call_chain.depth,
            "recoverable": recoverable,
            "timestamp": time.time(),
        })

    def set_agent_output(self, agent_id: str, response: AgentResponse) -> None:
        """Store the output from an agent."""
        self.agent_outputs[agent_id] = response

    def get_agent_output(self, agent_id: str) -> Optional[AgentResponse]:
        """Get the stored output from an agent."""
        return self.agent_outputs.get(agent_id)

    @asynccontextmanager
    async def timeout_scope(self, timeout: Optional[float] = None):
        """
        Async context manager for timeout handling.

        Usage:
            async with ctx.timeout_scope():
                await agent.run(...)
        """
        effective_timeout = min(
            timeout or self.layer_timeout,
            self.remaining_timeout
        )

        try:
            async with asyncio.timeout(effective_timeout):
                yield
        except asyncio.TimeoutError:
            raise TimeoutError(
                f"Layer timeout {effective_timeout}s exceeded at "
                f"{self.call_chain.get_path_string()}"
            )


# Custom exceptions

class CycleDetectedError(Exception):
    """Raised when a cycle is detected in the agent call chain."""
    pass


class MaxDepthExceededError(Exception):
    """Raised when the maximum nesting depth is exceeded."""
    pass


class AgentExecutionError(Exception):
    """Raised when an agent fails to execute."""

    def __init__(self, agent_id: str, message: str, cause: Optional[Exception] = None):
        self.agent_id = agent_id
        self.cause = cause
        super().__init__(f"Agent '{agent_id}' failed: {message}")


class WorkflowExecutionError(Exception):
    """Raised when a workflow fails to execute."""

    def __init__(self, workflow_id: str, message: str, errors: List[Dict[str, Any]]):
        self.workflow_id = workflow_id
        self.errors = errors
        super().__init__(f"Workflow '{workflow_id}' failed: {message}")
