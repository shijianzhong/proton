"""
Base class for system tools.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
from pydantic import BaseModel


class ToolParameterSchema(BaseModel):
    """Parameter schema for a system tool."""
    name: str
    type: str  # string, integer, number, boolean, array, object
    description: str
    required: bool = True
    default: Optional[Any] = None
    enum: Optional[List[Any]] = None


class SystemTool(ABC):
    """
    Abstract base class for system built-in tools.

    System tools are pre-defined capabilities that agents can use,
    such as file operations, web search, shell execution, etc.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Tool name (used in function calling)."""
        pass

    @property
    @abstractmethod
    def description(self) -> str:
        """Tool description for the LLM."""
        pass

    @property
    @abstractmethod
    def parameters(self) -> List[ToolParameterSchema]:
        """List of parameters this tool accepts."""
        pass

    @property
    def category(self) -> str:
        """Tool category for grouping in UI."""
        return "general"

    @property
    def requires_approval(self) -> bool:
        """Whether this tool requires user approval before execution."""
        return False

    @property
    def is_dangerous(self) -> bool:
        """Whether this tool can make destructive changes."""
        return False

    @abstractmethod
    async def execute(self, **kwargs: Any) -> str:
        """
        Execute the tool with the given parameters.

        Returns:
            A string result that will be passed back to the LLM.
        """
        pass

    def to_openai_schema(self) -> Dict[str, Any]:
        """Convert to OpenAI function calling schema."""
        properties = {}
        required = []

        for param in self.parameters:
            prop = {
                "type": param.type,
                "description": param.description,
            }
            if param.enum:
                prop["enum"] = param.enum
            if param.default is not None:
                prop["default"] = param.default

            properties[param.name] = prop

            if param.required:
                required.append(param.name)

        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                },
            },
        }

    def to_dict(self) -> Dict[str, Any]:
        """Convert tool info to dict for API responses."""
        return {
            "name": self.name,
            "description": self.description,
            "category": self.category,
            "parameters": [p.model_dump() for p in self.parameters],
            "requires_approval": self.requires_approval,
            "is_dangerous": self.is_dangerous,
        }
