"""
Copilot module for natural language workflow generation.

Provides:
- Multi-turn conversation for workflow design
- Workflow generation from natural language
- Workflow modification (patch) via conversation
- Session management for copilot interactions
"""

from .service import CopilotService, get_copilot_service
from .session_manager import SessionManager
from .schema import WorkflowPlan, AgentPlanTask

__all__ = [
    "CopilotService",
    "get_copilot_service",
    "SessionManager",
    "WorkflowPlan",
    "AgentPlanTask",
]
