"""
Base adapter interface for all agent types.

All adapters must implement the AgentAdapter protocol to ensure
consistent behavior across different agent sources.
"""

from abc import ABC, abstractmethod
from typing import Any, AsyncIterator, Dict, List, Optional, Type
import logging

from ..core.models import (
    AgentType,
    AgentResponse,
    AgentResponseUpdate,
    AgentCapabilities,
    ChatMessage,
)
from ..core.context import ExecutionContext
from ..core.agent_node import AgentNode

logger = logging.getLogger(__name__)


class AgentAdapter(ABC):
    """
    Abstract base class for agent adapters.

    All agent types (native, coze, dify, doubao, autogen, etc.)
    must implement this interface to work with the TreeExecutor.
    """

    def __init__(self, node: AgentNode):
        """
        Initialize the adapter with an agent node.

        Args:
            node: The AgentNode this adapter serves
        """
        self.node = node
        self._initialized = False

    @abstractmethod
    async def initialize(self) -> None:
        """
        Initialize the adapter.

        This is called once before the first run.
        Use this to set up connections, load models, etc.
        """
        pass

    @abstractmethod
    async def run(
        self,
        messages: List[ChatMessage],
        context: ExecutionContext,
        **kwargs: Any,
    ) -> AgentResponse:
        """
        Execute the agent with the given messages.

        Args:
            messages: The conversation history
            context: The execution context
            **kwargs: Additional arguments

        Returns:
            AgentResponse with the agent's output
        """
        pass

    @abstractmethod
    async def run_stream(
        self,
        messages: List[ChatMessage],
        context: ExecutionContext,
        **kwargs: Any,
    ) -> AsyncIterator[AgentResponseUpdate]:
        """
        Execute the agent with streaming output.

        Args:
            messages: The conversation history
            context: The execution context
            **kwargs: Additional arguments

        Yields:
            AgentResponseUpdate objects as the response is generated
        """
        pass

    @abstractmethod
    def get_capabilities(self) -> AgentCapabilities:
        """
        Get the agent's capabilities.

        Returns:
            AgentCapabilities describing what this agent can do
        """
        pass

    async def cleanup(self) -> None:
        """
        Clean up resources.

        Called when the adapter is no longer needed.
        Override to close connections, release resources, etc.
        """
        pass

    def _ensure_initialized(self) -> None:
        """Ensure the adapter has been initialized."""
        if not self._initialized:
            raise RuntimeError(
                f"Adapter for {self.node.id} not initialized. "
                "Call initialize() first."
            )


class AdapterFactory:
    """
    Factory for creating adapters based on agent type.

    Usage:
        factory = AdapterFactory()
        factory.register(AgentType.COZE, CozeAgentAdapter)

        adapter = factory.create(node)
    """

    _registry: Dict[AgentType, Type[AgentAdapter]] = {}

    @classmethod
    def register(
        cls,
        agent_type: AgentType,
        adapter_class: Type[AgentAdapter],
    ) -> None:
        """
        Register an adapter class for an agent type.

        Args:
            agent_type: The agent type this adapter handles
            adapter_class: The adapter class to use
        """
        cls._registry[agent_type] = adapter_class
        logger.info(f"Registered adapter {adapter_class.__name__} for {agent_type}")

    @classmethod
    def create(cls, node: AgentNode) -> AgentAdapter:
        """
        Create an adapter for the given agent node.

        Args:
            node: The agent node to create an adapter for

        Returns:
            An initialized AgentAdapter

        Raises:
            ValueError: If no adapter is registered for the agent type
        """
        adapter_class = cls._registry.get(node.type)
        if adapter_class is None:
            raise ValueError(
                f"No adapter registered for agent type: {node.type}. "
                f"Registered types: {list(cls._registry.keys())}"
            )

        return adapter_class(node)

    @classmethod
    async def create_async(cls, node: AgentNode) -> AgentAdapter:
        """
        Create and initialize an adapter asynchronously.

        Args:
            node: The agent node to create an adapter for

        Returns:
            An initialized AgentAdapter
        """
        adapter = cls.create(node)
        await adapter.initialize()
        return adapter

    @classmethod
    def get_registered_types(cls) -> List[AgentType]:
        """Get all registered agent types."""
        return list(cls._registry.keys())


# Helper function for creating adapters from nodes
async def create_adapter_for_node(node: AgentNode) -> AgentAdapter:
    """
    Convenience function to create an adapter for a node.

    This can be passed to TreeExecutor as the adapter_factory.
    """
    return await AdapterFactory.create_async(node)


def register_default_adapters() -> None:
    """
    Register all default adapters.

    Call this during application initialization.
    """
    from .workflow import WorkflowAdapter

    # Register workflow adapter for inter-workflow calling
    AdapterFactory.register(AgentType.WORKFLOW, WorkflowAdapter)

    logger.info("Default adapters registered")
