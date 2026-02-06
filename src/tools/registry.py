"""
System tool registry: manages all available system tools.
"""

from typing import Dict, List, Optional, Type
import logging

from .base import SystemTool

logger = logging.getLogger(__name__)


class SystemToolRegistry:
    """
    Registry for system built-in tools.

    System tools are globally available capabilities that can be
    enabled/disabled on a per-agent basis.
    """

    _instance: Optional["SystemToolRegistry"] = None

    def __init__(self):
        self._tools: Dict[str, SystemTool] = {}
        self._load_builtin_tools()

    def _load_builtin_tools(self):
        """Load all built-in system tools."""
        # File system tools
        from .filesystem import (
            FileReadTool,
            FileWriteTool,
            FileAppendTool,
            FileListTool,
            FileDeleteTool,
        )

        # Shell tools
        from .shell import ShellExecTool, ShellExecBackgroundTool

        # Web tools
        from .web import WebSearchTool, WebFetchTool, WebDownloadTool

        # Register all tools
        builtin_tools = [
            # Filesystem
            FileReadTool(),
            FileWriteTool(),
            FileAppendTool(),
            FileListTool(),
            FileDeleteTool(),
            # Shell
            ShellExecTool(),
            ShellExecBackgroundTool(),
            # Web
            WebSearchTool(),
            WebFetchTool(),
            WebDownloadTool(),
        ]

        # Email tools (optional - requires aiosmtplib)
        try:
            from .email import SendEmailTool, CheckEmailConfigTool
            builtin_tools.append(SendEmailTool())
            builtin_tools.append(CheckEmailConfigTool())
        except ImportError as e:
            logger.warning(f"Email tools not available (missing dependency): {e}")

        for tool in builtin_tools:
            self.register(tool)

        logger.info(f"Loaded {len(self._tools)} system tools")

    def register(self, tool: SystemTool) -> None:
        """Register a system tool."""
        self._tools[tool.name] = tool
        logger.debug(f"Registered system tool: {tool.name}")

    def unregister(self, name: str) -> Optional[SystemTool]:
        """Unregister a system tool."""
        return self._tools.pop(name, None)

    def get(self, name: str) -> Optional[SystemTool]:
        """Get a tool by name."""
        return self._tools.get(name)

    def list_all(self) -> List[SystemTool]:
        """List all registered tools."""
        return list(self._tools.values())

    def list_by_category(self, category: str) -> List[SystemTool]:
        """List tools by category."""
        return [t for t in self._tools.values() if t.category == category]

    def get_categories(self) -> List[str]:
        """Get all unique categories."""
        return list(set(t.category for t in self._tools.values()))

    def get_openai_schemas(self, tool_names: Optional[List[str]] = None) -> List[Dict]:
        """
        Get OpenAI function calling schemas for the specified tools.

        Args:
            tool_names: List of tool names to include. If None, includes all tools.

        Returns:
            List of OpenAI function calling schemas.
        """
        if tool_names is None:
            tools = self._tools.values()
        else:
            tools = [self._tools[name] for name in tool_names if name in self._tools]

        return [tool.to_openai_schema() for tool in tools]

    async def execute(self, tool_name: str, **kwargs) -> str:
        """
        Execute a tool by name.

        Args:
            tool_name: Name of the tool to execute.
            **kwargs: Arguments to pass to the tool.

        Returns:
            Tool execution result as a string.
        """
        tool = self._tools.get(tool_name)
        if not tool:
            return f"Error: Unknown tool '{tool_name}'"

        try:
            return await tool.execute(**kwargs)
        except Exception as e:
            logger.error(f"Error executing tool {tool_name}: {e}")
            return f"Error executing tool: {e}"

    def to_list(self) -> List[Dict]:
        """Convert all tools to dict list for API responses."""
        return [tool.to_dict() for tool in self._tools.values()]


# Singleton instance
_system_tool_registry: Optional[SystemToolRegistry] = None


def get_system_tool_registry() -> SystemToolRegistry:
    """Get the global system tool registry instance."""
    global _system_tool_registry
    if _system_tool_registry is None:
        _system_tool_registry = SystemToolRegistry()
    return _system_tool_registry
