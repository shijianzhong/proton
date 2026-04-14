import json
import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from pydantic import ValidationError

from ..core.models import MCPServerConfig, InstalledMCPServer

logger = logging.getLogger(__name__)

class MCPManager:
    """Manages installed MCP servers globally."""

    def __init__(self, storage_path: str = "data/mcp/registry.json"):
        self._storage_path = Path(storage_path)
        self._servers: Dict[str, InstalledMCPServer] = {}
        self._load_registry()

    def _load_registry(self) -> None:
        """Load MCP servers from registry."""
        if not self._storage_path.exists():
            self._storage_path.parent.mkdir(parents=True, exist_ok=True)
            self._save_registry()
            return

        try:
            with open(self._storage_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            for server_id, server_data in data.items():
                try:
                    self._servers[server_id] = InstalledMCPServer(**server_data)
                except ValidationError as e:
                    logger.error(f"Failed to load MCP server {server_id}: {e}")

            logger.info(f"Loaded {len(self._servers)} MCP servers from registry")
        except Exception as e:
            logger.error(f"Failed to load MCP registry: {e}")

    def _save_registry(self) -> None:
        """Save MCP servers to registry."""
        try:
            self._storage_path.parent.mkdir(parents=True, exist_ok=True)
            data = {
                server_id: server.model_dump(mode="json")
                for server_id, server in self._servers.items()
            }
            with open(self._storage_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Failed to save MCP registry: {e}")

    def register_server(
        self,
        config: MCPServerConfig,
        description: str = "",
        author: Optional[str] = None,
        version: str = "1.0.0",
        tags: List[str] = None
    ) -> InstalledMCPServer:
        """Register a new global MCP server."""
        server_id = f"mcp_{uuid.uuid4().hex[:8]}"
        
        installed_server = InstalledMCPServer(
            id=server_id,
            config=config,
            description=description,
            author=author,
            version=version,
            tags=tags or ["mcp"],
            installed_at=datetime.now()
        )
        
        self._servers[server_id] = installed_server
        self._save_registry()
        logger.info(f"Registered MCP server: {config.name} ({server_id})")
        
        return installed_server

    def unregister_server(self, server_id: str) -> bool:
        """Remove an MCP server from the registry."""
        if server_id in self._servers:
            name = self._servers[server_id].config.name
            del self._servers[server_id]
            self._save_registry()
            logger.info(f"Unregistered MCP server: {name} ({server_id})")
            return True
        return False

    def get_server(self, server_id: str) -> Optional[InstalledMCPServer]:
        """Get an installed MCP server by ID."""
        return self._servers.get(server_id)

    def list_servers(self, enabled_only: bool = False) -> List[InstalledMCPServer]:
        """List all installed MCP servers."""
        if enabled_only:
            return [s for s in self._servers.values() if s.enabled]
        return list(self._servers.values())

    def toggle_server(self, server_id: str, enabled: bool) -> bool:
        """Enable or disable an MCP server."""
        if server_id in self._servers:
            self._servers[server_id].enabled = enabled
            self._save_registry()
            return True
        return False

    def bind_server_to_agent(self, server_id: str, agent_id: str) -> bool:
        """Bind an MCP server to an agent."""
        server = self._servers.get(server_id)
        if not server:
            return False

        if agent_id not in server.agent_ids:
            server.agent_ids.append(agent_id)
            self._save_registry()
            logger.info(f"Bound MCP server {server_id} to agent {agent_id}")
        return True

    def unbind_server_from_agent(self, server_id: str, agent_id: str) -> bool:
        """Unbind an MCP server from an agent."""
        server = self._servers.get(server_id)
        if not server:
            return False

        if agent_id in server.agent_ids:
            server.agent_ids.remove(agent_id)
            self._save_registry()
            logger.info(f"Unbound MCP server {server_id} from agent {agent_id}")
        return True

    def get_servers_for_agent(self, agent_id: str) -> List[InstalledMCPServer]:
        """Get all MCP servers bound to a specific agent."""
        return [
            server for server in self._servers.values()
            if agent_id in server.agent_ids and server.enabled
        ]


# Global MCP manager instance
_mcp_manager: Optional[MCPManager] = None

def get_mcp_manager() -> MCPManager:
    """Get the global MCP manager instance."""
    global _mcp_manager
    if _mcp_manager is None:
        _mcp_manager = MCPManager()
    return _mcp_manager