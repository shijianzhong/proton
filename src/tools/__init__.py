"""
System built-in tools for Proton Agent Platform.

These tools provide core capabilities that can be used by any built-in agent:
- File operations (read, write, list, edit)
- Shell command execution
- Web operations (search, fetch, download)
- Email operations (send_email, check_email_config)
- Memory/knowledge management
"""

from .registry import SystemToolRegistry, get_system_tool_registry
from .base import SystemTool
from .web import get_search_config, SearchConfig

__all__ = [
    "SystemToolRegistry",
    "get_system_tool_registry",
    "SystemTool",
    "get_search_config",
    "SearchConfig",
]
