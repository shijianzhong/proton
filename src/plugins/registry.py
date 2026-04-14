"""
Plugin registry for managing MCP, Skill, and RAG plugins.
"""

import logging
from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, List, Optional, TYPE_CHECKING
from dataclasses import dataclass, field

from ..core.models import (
    PluginConfig,
    MCPServerConfig,
    SkillConfig,
    RAGSourceConfig,
)

if TYPE_CHECKING:
    from ..core.agent_node import AgentNode
    from .mcp_plugin import MCPPlugin
    from .rag_plugin import RAGPlugin
    from .skill_plugin import SkillPlugin

logger = logging.getLogger(__name__)


@dataclass
class Tool:
    """
    Represents a tool that can be used by an agent.

    Tools are the unified interface for:
    - MCP tools (from MCP servers)
    - Skills (Python functions)
    - RAG queries (retrieval augmented generation)
    """
    name: str
    description: str
    parameters_schema: Dict[str, Any] = field(default_factory=dict)
    handler: Optional[Callable[..., Any]] = None
    source: str = ""  # mcp, skill, rag
    approval_required: bool = False
    is_dangerous: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)

    async def execute(self, **kwargs: Any) -> Any:
        """Execute the tool with given parameters."""
        if self.handler is None:
            raise RuntimeError(f"Tool {self.name} has no handler")
        result = self.handler(**kwargs)
        if hasattr(result, '__await__'):
            return await result
        return result


class Plugin(ABC):
    """Base class for all plugins."""

    def __init__(self, config: PluginConfig):
        self.config = config
        self._initialized = False
        self._tools: List[Tool] = []

    @abstractmethod
    async def initialize(self) -> None:
        """Initialize the plugin."""
        pass

    @abstractmethod
    async def cleanup(self) -> None:
        """Clean up plugin resources."""
        pass

    @abstractmethod
    def get_tools(self) -> List[Tool]:
        """Get all tools provided by this plugin."""
        pass

    @property
    def is_enabled(self) -> bool:
        """Check if the plugin is enabled."""
        return self.config.enabled

    @property
    def plugin_type(self) -> str:
        """Get the plugin type."""
        return self.config.type


class PluginRegistry:
    """
    Central registry for managing all plugins.

    The registry:
    - Manages plugin lifecycle (init, cleanup)
    - Provides tools to agents
    - Handles plugin dependencies
    """

    def __init__(self):
        self._plugins: Dict[str, Plugin] = {}
        self._agent_plugins: Dict[str, List[str]] = {}  # agent_id -> [plugin_ids]
        self._initialized = False

    async def register_mcp(
        self,
        config: MCPServerConfig,
        agent_id: Optional[str] = None,
    ) -> "MCPPlugin":
        """
        Register an MCP server plugin.

        Args:
            config: MCP server configuration
            agent_id: Optional agent ID to associate with

        Returns:
            The created MCPPlugin
        """
        from .mcp_plugin import MCPPlugin

        plugin_config = PluginConfig(
            type="mcp",
            enabled=True,
            mcp_config=config,
        )
        plugin = MCPPlugin(plugin_config)
        await plugin.initialize()

        plugin_id = f"mcp_{config.name}"
        self._plugins[plugin_id] = plugin

        if agent_id:
            self._associate_plugin(agent_id, plugin_id)

        logger.info(f"Registered MCP plugin: {config.name}")
        return plugin

    async def register_skill(
        self,
        config: SkillConfig,
        agent_id: Optional[str] = None,
    ) -> "SkillPlugin":
        """
        Register a skill plugin.

        Args:
            config: Skill configuration
            agent_id: Optional agent ID to associate with

        Returns:
            The created SkillPlugin
        """
        from .skill_plugin import SkillPlugin

        plugin_config = PluginConfig(
            type="skill",
            enabled=True,
            skill_config=config,
        )
        plugin = SkillPlugin(plugin_config)
        await plugin.initialize()

        plugin_id = f"skill_{config.name}"
        self._plugins[plugin_id] = plugin

        if agent_id:
            self._associate_plugin(agent_id, plugin_id)

        logger.info(f"Registered skill plugin: {config.name}")
        return plugin

    async def register_rag(
        self,
        config: RAGSourceConfig,
        agent_id: Optional[str] = None,
    ) -> "RAGPlugin":
        """
        Register a RAG source plugin.

        Args:
            config: RAG source configuration
            agent_id: Optional agent ID to associate with

        Returns:
            The created RAGPlugin
        """
        from .rag_plugin import RAGPlugin

        plugin_config = PluginConfig(
            type="rag",
            enabled=True,
            rag_config=config,
        )
        plugin = RAGPlugin(plugin_config)
        await plugin.initialize()

        plugin_id = f"rag_{config.name}"
        self._plugins[plugin_id] = plugin

        if agent_id:
            self._associate_plugin(agent_id, plugin_id)

        logger.info(f"Registered RAG plugin: {config.name}")
        return plugin

    def _associate_plugin(self, agent_id: str, plugin_id: str) -> None:
        """Associate a plugin with an agent."""
        if agent_id not in self._agent_plugins:
            self._agent_plugins[agent_id] = []
        if plugin_id not in self._agent_plugins[agent_id]:
            self._agent_plugins[agent_id].append(plugin_id)

    def get_plugins_for_agent(self, agent_id: str) -> List[Plugin]:
        """Get all plugins associated with an agent."""
        plugin_ids = self._agent_plugins.get(agent_id, [])
        return [self._plugins[pid] for pid in plugin_ids if pid in self._plugins]

    def get_tools_for_agent(self, agent_id: str) -> List[Tool]:
        """Get all tools available to an agent."""
        tools = []
        for plugin in self.get_plugins_for_agent(agent_id):
            if plugin.is_enabled:
                tools.extend(plugin.get_tools())
        return tools

    def get_all_plugins(self) -> Dict[str, Plugin]:
        """Get all registered plugins."""
        return self._plugins.copy()

    def get_plugin(self, plugin_id: str) -> Optional[Plugin]:
        """Get a plugin by ID."""
        return self._plugins.get(plugin_id)

    async def remove_plugin(self, plugin_id: str) -> Optional[Plugin]:
        """Remove and cleanup a plugin."""
        plugin = self._plugins.pop(plugin_id, None)
        if plugin:
            await plugin.cleanup()

            # Remove from agent associations
            for agent_id in self._agent_plugins:
                if plugin_id in self._agent_plugins[agent_id]:
                    self._agent_plugins[agent_id].remove(plugin_id)

        return plugin

    async def cleanup_all(self) -> None:
        """Clean up all plugins."""
        for plugin_id, plugin in list(self._plugins.items()):
            try:
                await plugin.cleanup()
            except Exception as e:
                logger.error(f"Error cleaning up plugin {plugin_id}: {e}")
        self._plugins.clear()
        self._agent_plugins.clear()

    async def initialize_for_node(self, node: "AgentNode") -> None:
        """
        Initialize all plugins for an agent node.

        This reads the node's globally bound plugins (Skills and MCPs) from their respective managers.
        """
        # 1. Register global MCP servers bound to this agent
        from .mcp_manager import get_mcp_manager
        mcp_manager = get_mcp_manager()
        bound_mcps = mcp_manager.get_servers_for_agent(node.id)
        for mcp in bound_mcps:
            await self.register_mcp(mcp.config, node.id)

        # 2. Register global Skills bound to this agent
        from .skill_manager import get_skill_manager
        skill_manager = get_skill_manager()
        bound_skills = skill_manager.get_skills_for_agent(node.id)
        for skill in bound_skills:
            skill_config = skill_manager.get_skill_config(skill.id)
            if skill_config:
                await self.register_skill(skill_config, node.id)

        # 3. Register RAG sources (these are still local to the agent config for now)
        for rag_config in node.config.rag_sources:
            await self.register_rag(rag_config, node.id)

        logger.info(
            f"Initialized {len(self.get_plugins_for_agent(node.id))} plugins for agent {node.id}"
        )


# Global plugin registry instance
_global_registry: Optional[PluginRegistry] = None


def get_plugin_registry() -> PluginRegistry:
    """Get the global plugin registry."""
    global _global_registry
    if _global_registry is None:
        _global_registry = PluginRegistry()
    return _global_registry
