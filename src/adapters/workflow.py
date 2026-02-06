"""
Adapter for executing workflows as sub-agents.

Allows workflows to reference and call other workflows,
enabling workflow composition and reuse.
"""

import logging
from typing import Any, AsyncIterator, Dict, List, Optional

from .base import AgentAdapter
from ..core.models import (
    AgentResponse,
    AgentResponseUpdate,
    AgentCapabilities,
    ChatMessage,
    MessageRole,
)
from ..core.context import ExecutionContext, CycleDetectedError
from ..core.agent_node import AgentNode

logger = logging.getLogger(__name__)


class WorkflowAdapter(AgentAdapter):
    """
    Adapter that executes a referenced workflow as a sub-node.

    This allows workflows to call other workflows, enabling:
    - Workflow composition and reuse
    - Modular workflow design
    - Hierarchical workflow structures
    """

    def __init__(self, node: AgentNode):
        """
        Initialize the workflow adapter.

        Args:
            node: The AgentNode with workflow_config specifying the referenced workflow
        """
        super().__init__(node)
        self.referenced_workflow = None
        self._workflow_manager = None

    async def initialize(self) -> None:
        """
        Initialize the adapter by loading the referenced workflow.

        Raises:
            ValueError: If workflow config is missing or workflow not found
        """
        config = self.node.config
        if not config or not config.workflow_config:
            raise ValueError(
                f"Workflow config required for agent {self.node.id}"
            )

        workflow_id = config.workflow_config.workflow_id

        # Import here to avoid circular dependency
        from ..orchestration.workflow import get_workflow_manager

        self._workflow_manager = get_workflow_manager()
        self.referenced_workflow = await self._workflow_manager.get_workflow(workflow_id)

        if not self.referenced_workflow:
            raise ValueError(
                f"Referenced workflow not found: {workflow_id}"
            )

        logger.info(
            f"WorkflowAdapter initialized for {self.node.id}, "
            f"referencing workflow {workflow_id}"
        )
        self._initialized = True

    async def run(
        self,
        messages: List[ChatMessage],
        context: ExecutionContext,
        **kwargs: Any,
    ) -> AgentResponse:
        """
        Execute the referenced workflow.

        Args:
            messages: The conversation history
            context: The execution context
            **kwargs: Additional arguments

        Returns:
            AgentResponse with the workflow's output

        Raises:
            CycleDetectedError: If circular workflow reference detected
        """
        self._ensure_initialized()

        workflow_id = self.node.config.workflow_config.workflow_id

        # Check for circular reference
        if self._has_circular_reference(context, workflow_id):
            raise CycleDetectedError(
                f"Circular workflow reference detected: {workflow_id} "
                f"is already in the call chain"
            )

        # Get input message
        input_message = messages[-1].content if messages else ""

        # Apply input mapping if configured
        mapped_input = self._apply_input_mapping(input_message, context)

        # Add workflow to tracking
        context.call_chain.add_workflow(workflow_id)

        try:
            # Execute the referenced workflow
            result = await self.referenced_workflow.run(mapped_input, context)

            # Build response from workflow result
            if result.response:
                output_messages = result.response.messages
            else:
                # Handle error or empty response
                error_msg = result.error or "Workflow returned no response"
                output_messages = [
                    ChatMessage(
                        role=MessageRole.ASSISTANT,
                        content=f"[Workflow Error] {error_msg}"
                    )
                ]

            # Apply output mapping
            response = AgentResponse(
                messages=output_messages,
                metadata={
                    "workflow_id": workflow_id,
                    "execution_id": result.execution_id,
                    "duration_ms": result.duration_ms,
                }
            )

            return self._apply_output_mapping(response, context)

        except Exception as e:
            logger.error(f"Error executing workflow {workflow_id}: {e}")
            return AgentResponse(
                messages=[
                    ChatMessage(
                        role=MessageRole.ASSISTANT,
                        content=f"[Workflow Execution Error] {str(e)}"
                    )
                ],
                metadata={"error": str(e), "workflow_id": workflow_id}
            )

    async def run_stream(
        self,
        messages: List[ChatMessage],
        context: ExecutionContext,
        **kwargs: Any,
    ) -> AsyncIterator[AgentResponseUpdate]:
        """
        Execute the referenced workflow with streaming output.

        Args:
            messages: The conversation history
            context: The execution context
            **kwargs: Additional arguments

        Yields:
            AgentResponseUpdate objects as the response is generated
        """
        self._ensure_initialized()

        workflow_id = self.node.config.workflow_config.workflow_id

        # Check for circular reference
        if self._has_circular_reference(context, workflow_id):
            yield AgentResponseUpdate(
                delta_content=f"[Error] Circular workflow reference: {workflow_id}",
                is_complete=True,
            )
            return

        # Get input message
        input_message = messages[-1].content if messages else ""
        mapped_input = self._apply_input_mapping(input_message, context)

        # Add workflow to tracking
        context.call_chain.add_workflow(workflow_id)

        try:
            async for update in self.referenced_workflow.run_stream(mapped_input, context):
                yield update
        except Exception as e:
            logger.error(f"Error streaming workflow {workflow_id}: {e}")
            yield AgentResponseUpdate(
                delta_content=f"[Workflow Error] {str(e)}",
                is_complete=True,
            )

    def get_capabilities(self) -> AgentCapabilities:
        """Get the capabilities of this adapter."""
        return AgentCapabilities(
            supports_streaming=True,
            supports_tools=True,
            supports_vision=False,
            supports_audio=False,
            supports_files=False,
            max_context_length=128000,
        )

    async def cleanup(self) -> None:
        """Clean up resources."""
        self.referenced_workflow = None
        self._workflow_manager = None

    def _has_circular_reference(
        self,
        context: ExecutionContext,
        workflow_id: str
    ) -> bool:
        """
        Check if this workflow is already in the call chain.

        Args:
            context: The execution context
            workflow_id: The workflow ID to check

        Returns:
            True if circular reference detected
        """
        return workflow_id in context.call_chain.get_workflow_ids()

    def _apply_input_mapping(
        self,
        input_message: str,
        context: ExecutionContext
    ) -> str:
        """
        Apply input mapping to transform parent context to child input.

        Args:
            input_message: The original input message
            context: The execution context

        Returns:
            Transformed input message
        """
        config = self.node.config.workflow_config
        if not config.input_mapping:
            return input_message

        # Apply input mappings from shared state
        mapped_parts = [input_message]
        for target_key, source_key in config.input_mapping.items():
            if source_key in context.shared_state:
                value = context.shared_state[source_key]
                mapped_parts.append(f"\n[{target_key}]: {value}")

        return "".join(mapped_parts)

    def _apply_output_mapping(
        self,
        response: AgentResponse,
        context: ExecutionContext
    ) -> AgentResponse:
        """
        Apply output mapping to transform child output to parent context.

        Args:
            response: The workflow response
            context: The execution context

        Returns:
            Potentially modified response with mapped outputs
        """
        config = self.node.config.workflow_config
        if not config.output_mapping:
            return response

        # Store mapped outputs in shared state
        for target_key, source_key in config.output_mapping.items():
            # Try to extract from response content
            if response.messages:
                content = response.messages[-1].content
                context.shared_state[target_key] = content

            # Also check metadata
            if source_key in response.metadata:
                context.shared_state[target_key] = response.metadata[source_key]

        return response
