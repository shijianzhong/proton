"""
AgentNode represents a node in the agent tree structure.

Each node can have:
- Parent node (except root)
- Child nodes
- Plugins (MCP, Skill, RAG)
- Routing strategy for child invocation
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, TYPE_CHECKING
from uuid import uuid4

from .models import (
    AgentType,
    AgentConfig,
    PluginConfig,
    RoutingStrategy,
    RetryPolicy,
    AgentCapabilities,
)

if TYPE_CHECKING:
    from ..adapters.base import AgentAdapter


@dataclass
class AgentNode:
    """
    A node in the agent tree hierarchy.

    Attributes:
        id: Unique identifier for this agent
        name: Human-readable name
        description: Description of what this agent does
        type: Type of agent (native, coze, dify, etc.)
        config: Agent-specific configuration
        parent_id: ID of parent node (None for root)
        children: List of child agent IDs
        plugins: List of plugins attached to this agent
        routing_strategy: How to route to children
        max_depth: Maximum recursion depth from this node
        timeout: Execution timeout for this agent
        retry_policy: How to handle retries
        enabled: Whether this agent is active
    """
    # Identity
    id: str = field(default_factory=lambda: str(uuid4()))
    name: str = ""
    description: str = ""

    # Type and configuration
    type: AgentType = AgentType.NATIVE
    config: AgentConfig = field(default_factory=AgentConfig)

    # Tree structure
    parent_id: Optional[str] = None
    children: List[str] = field(default_factory=list)

    # Plugins
    plugins: List[PluginConfig] = field(default_factory=list)

    # Execution settings
    routing_strategy: RoutingStrategy = RoutingStrategy.SEQUENTIAL
    max_depth: int = 5
    timeout: float = 60.0
    retry_policy: RetryPolicy = field(default_factory=RetryPolicy)

    # Conditional routing configuration
    routing_conditions: Dict[str, str] = field(default_factory=dict)
    # Format: {"condition_expression": "target_agent_id"}
    # e.g., {"intent == 'refund'": "refund_agent_id"}

    # State
    enabled: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)

    # Runtime (not persisted)
    _adapter: Optional["AgentAdapter"] = field(default=None, repr=False)
    _capabilities: Optional[AgentCapabilities] = field(default=None, repr=False)

    def __post_init__(self):
        if not self.name:
            self.name = f"agent_{self.id[:8]}"

    @property
    def is_root(self) -> bool:
        """Check if this is a root node (no parent)."""
        return self.parent_id is None

    @property
    def is_leaf(self) -> bool:
        """Check if this is a leaf node (no children)."""
        return len(self.children) == 0

    @property
    def has_children(self) -> bool:
        """Check if this node has children."""
        return len(self.children) > 0

    @property
    def adapter(self) -> Optional["AgentAdapter"]:
        """Get the agent adapter."""
        return self._adapter

    @adapter.setter
    def adapter(self, value: "AgentAdapter") -> None:
        """Set the agent adapter."""
        self._adapter = value

    @property
    def capabilities(self) -> AgentCapabilities:
        """Get agent capabilities."""
        if self._capabilities:
            return self._capabilities
        if self._adapter:
            return self._adapter.get_capabilities()
        return AgentCapabilities()

    def add_child(self, child_id: str) -> None:
        """Add a child agent to this node."""
        if child_id not in self.children:
            self.children.append(child_id)

    def remove_child(self, child_id: str) -> None:
        """Remove a child agent from this node."""
        if child_id in self.children:
            self.children.remove(child_id)

    def add_plugin(self, plugin: PluginConfig) -> None:
        """Add a plugin to this agent."""
        self.plugins.append(plugin)

    def remove_plugin(self, plugin_name: str) -> None:
        """Remove a plugin by name."""
        self.plugins = [
            p for p in self.plugins
            if not (
                (p.mcp_config and p.mcp_config.name == plugin_name) or
                (p.skill_config and p.skill_config.name == plugin_name) or
                (p.rag_config and p.rag_config.name == plugin_name)
            )
        ]

    def get_mcp_servers(self) -> List[PluginConfig]:
        """Get all MCP server plugins."""
        return [p for p in self.plugins if p.type == "mcp" and p.enabled]

    def get_skills(self) -> List[PluginConfig]:
        """Get all skill plugins."""
        return [p for p in self.plugins if p.type == "skill" and p.enabled]

    def get_rag_sources(self) -> List[PluginConfig]:
        """Get all RAG source plugins."""
        return [p for p in self.plugins if p.type == "rag" and p.enabled]

    def set_routing_condition(self, condition: str, target_id: str) -> None:
        """
        Set a routing condition for conditional strategy.

        Args:
            condition: A condition expression (e.g., "intent == 'refund'")
            target_id: The agent ID to route to when condition is true
        """
        self.routing_conditions[condition] = target_id

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "type": self.type.value,
            "config": self.config.model_dump(),
            "parent_id": self.parent_id,
            "children": self.children,
            "plugins": [p.model_dump() for p in self.plugins],
            "routing_strategy": self.routing_strategy.value,
            "max_depth": self.max_depth,
            "timeout": self.timeout,
            "retry_policy": self.retry_policy.model_dump(),
            "routing_conditions": self.routing_conditions,
            "enabled": self.enabled,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AgentNode":
        """Create from dictionary."""
        return cls(
            id=data.get("id", str(uuid4())),
            name=data.get("name", ""),
            description=data.get("description", ""),
            type=AgentType(data.get("type", "native")),
            config=AgentConfig(**data.get("config", {})),
            parent_id=data.get("parent_id"),
            children=data.get("children", []),
            plugins=[PluginConfig(**p) for p in data.get("plugins", [])],
            routing_strategy=RoutingStrategy(data.get("routing_strategy", "sequential")),
            max_depth=data.get("max_depth", 5),
            timeout=data.get("timeout", 60.0),
            retry_policy=RetryPolicy(**data.get("retry_policy", {})),
            routing_conditions=data.get("routing_conditions", {}),
            enabled=data.get("enabled", True),
            metadata=data.get("metadata", {}),
        )


class AgentTree:
    """
    Manages a tree of AgentNodes.

    Provides methods for:
    - Building and modifying the tree structure
    - Traversing the tree
    - Validating the tree structure
    """

    def __init__(self):
        self.nodes: Dict[str, AgentNode] = {}
        self.root_id: Optional[str] = None

    def add_node(self, node: AgentNode) -> None:
        """Add a node to the tree."""
        self.nodes[node.id] = node

        # Set as root if it's the first node or has no parent
        # Use 'not self.root_id' to handle both None and empty string ""
        if node.is_root and (not self.root_id or node.id == self.root_id):
            self.root_id = node.id

        # Update parent's children list
        if node.parent_id and node.parent_id in self.nodes:
            self.nodes[node.parent_id].add_child(node.id)

    def remove_node(self, node_id: str) -> Optional[AgentNode]:
        """
        Remove a node from the tree.

        Also removes all descendants and updates parent.
        """
        if node_id not in self.nodes:
            return None

        node = self.nodes[node_id]

        # Remove from parent's children
        if node.parent_id and node.parent_id in self.nodes:
            self.nodes[node.parent_id].remove_child(node_id)

        # Recursively remove children
        for child_id in node.children.copy():
            self.remove_node(child_id)

        # Remove this node
        del self.nodes[node_id]

        # Update root if needed
        if self.root_id == node_id:
            self.root_id = None

        return node

    def get_node(self, node_id: str) -> Optional[AgentNode]:
        """Get a node by ID."""
        return self.nodes.get(node_id)

    def get_root(self) -> Optional[AgentNode]:
        """Get the root node."""
        if self.root_id:
            return self.nodes.get(self.root_id)
        return None

    def get_children(self, node_id: str) -> List[AgentNode]:
        """Get all child nodes of a node."""
        node = self.nodes.get(node_id)
        if not node:
            return []
        return [self.nodes[cid] for cid in node.children if cid in self.nodes]

    def get_parent(self, node_id: str) -> Optional[AgentNode]:
        """Get the parent node of a node."""
        node = self.nodes.get(node_id)
        if not node or not node.parent_id:
            return None
        return self.nodes.get(node.parent_id)

    def get_ancestors(self, node_id: str) -> List[AgentNode]:
        """Get all ancestor nodes from root to parent."""
        ancestors = []
        current = self.get_parent(node_id)
        while current:
            ancestors.insert(0, current)
            current = self.get_parent(current.id)
        return ancestors

    def get_descendants(self, node_id: str) -> List[AgentNode]:
        """Get all descendant nodes (depth-first)."""
        descendants = []
        node = self.nodes.get(node_id)
        if not node:
            return descendants

        for child_id in node.children:
            child = self.nodes.get(child_id)
            if child:
                descendants.append(child)
                descendants.extend(self.get_descendants(child_id))

        return descendants

    def get_depth(self, node_id: str) -> int:
        """Get the depth of a node in the tree."""
        return len(self.get_ancestors(node_id))

    def get_max_depth(self) -> int:
        """Get the maximum depth of the tree."""
        if not self.nodes:
            return 0
        return max(self.get_depth(nid) for nid in self.nodes)

    def validate(self) -> List[str]:
        """
        Validate the tree structure.

        Returns a list of validation errors (empty if valid).
        """
        errors = []

        # Check for root
        if not self.root_id:
            errors.append("Tree has no root node")
            return errors

        if self.root_id not in self.nodes:
            errors.append(f"Root ID {self.root_id} not found in nodes")
            return errors

        # Check all nodes
        visited = set()
        orphans = []

        for node_id, node in self.nodes.items():
            # Check parent references
            if node.parent_id and node.parent_id not in self.nodes:
                errors.append(
                    f"Node {node_id} references non-existent parent {node.parent_id}"
                )

            # Check child references
            for child_id in node.children:
                if child_id not in self.nodes:
                    errors.append(
                        f"Node {node_id} references non-existent child {child_id}"
                    )

            # Track for orphan detection
            if node.parent_id:
                visited.add(node_id)

        # Check for orphans (nodes not reachable from root)
        reachable = {self.root_id}
        to_visit = [self.root_id]
        while to_visit:
            current_id = to_visit.pop()
            current = self.nodes.get(current_id)
            if current:
                for child_id in current.children:
                    if child_id not in reachable:
                        reachable.add(child_id)
                        to_visit.append(child_id)

        orphans = set(self.nodes.keys()) - reachable
        if orphans:
            errors.append(f"Orphan nodes detected: {orphans}")

        return errors

    def to_dict(self) -> Dict[str, Any]:
        """Convert tree to dictionary for serialization."""
        return {
            "root_id": self.root_id,
            "nodes": {nid: node.to_dict() for nid, node in self.nodes.items()},
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AgentTree":
        """Create tree from dictionary."""
        tree = cls()
        tree.root_id = data.get("root_id")
        for node_id, node_data in data.get("nodes", {}).items():
            tree.nodes[node_id] = AgentNode.from_dict(node_data)
        return tree

    def __len__(self) -> int:
        return len(self.nodes)

    def __contains__(self, node_id: str) -> bool:
        return node_id in self.nodes

    def __iter__(self):
        return iter(self.nodes.values())
