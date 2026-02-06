"""
Tools for Copilot to generate and modify workflows.

These are the tools available to the Copilot LLM for
creating and modifying workflows based on user requirements.
"""

import json
import logging
from typing import Any, Dict, List, Optional

from ..core.models import (
    AgentType,
    AgentConfig,
    RoutingStrategy,
    BuiltinAgentDefinition,
    OutputFormat,
    CopilotSession,
)
from ..core.agent_node import AgentNode
from ..orchestration.workflow import WorkflowManager
from .schema import WorkflowPlan, WorkflowPatch, AgentPlanTask, PatchOperation

logger = logging.getLogger(__name__)


# OpenAI function tool definitions for the LLM
COPILOT_TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "generate_workflow",
            "description": "Create a complete new workflow from a plan. Use this when the user wants to create a new workflow.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "Name of the workflow"
                    },
                    "description": {
                        "type": "string",
                        "description": "Description of what the workflow does"
                    },
                    "agents": {
                        "type": "array",
                        "description": "List of agents in the workflow",
                        "items": {
                            "type": "object",
                            "properties": {
                                "id": {
                                    "type": "string",
                                    "description": "Local ID for this agent (e.g. agent-1, agent-2)"
                                },
                                "name": {
                                    "type": "string",
                                    "description": "Display name of the agent"
                                },
                                "description": {
                                    "type": "string",
                                    "description": "What this agent does"
                                },
                                "type": {
                                    "type": "string",
                                    "enum": ["builtin", "native", "workflow"],
                                    "description": "Agent type, typically 'builtin'"
                                },
                                "system_prompt": {
                                    "type": "string",
                                    "description": "Detailed system prompt for the agent"
                                },
                                "parent_id": {
                                    "type": ["string", "null"],
                                    "description": "Parent agent's local ID (null for root)"
                                },
                                "routing_strategy": {
                                    "type": "string",
                                    "enum": ["sequential", "parallel", "conditional", "coordinator", "handoff", "hierarchical"],
                                    "description": "How to route to child agents"
                                },
                                "routing_conditions": {
                                    "type": "object",
                                    "description": "Conditions for conditional routing (keyword: agent_id mapping)",
                                    "additionalProperties": {"type": "string"}
                                },
                                "tools": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                    "description": "System tools to enable (e.g. web_search, file_write)"
                                },
                                "model": {
                                    "type": "string",
                                    "description": "Model to use (default: gpt-4)"
                                },
                                "temperature": {
                                    "type": "number",
                                    "description": "Temperature setting (0.0-1.0)"
                                }
                            },
                            "required": ["id", "name", "description"]
                        }
                    }
                },
                "required": ["title", "description", "agents"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "patch_workflow",
            "description": "Modify an existing workflow by adding, updating, or deleting agents.",
            "parameters": {
                "type": "object",
                "properties": {
                    "workflow_id": {
                        "type": "string",
                        "description": "The workflow ID to modify"
                    },
                    "description": {
                        "type": "string",
                        "description": "Description of what changes are being made"
                    },
                    "operations": {
                        "type": "array",
                        "description": "List of patch operations",
                        "items": {
                            "type": "object",
                            "properties": {
                                "operation": {
                                    "type": "string",
                                    "enum": ["add", "update", "delete"],
                                    "description": "Type of operation"
                                },
                                "agent_id": {
                                    "type": "string",
                                    "description": "Agent ID for update/delete operations"
                                },
                                "parent_id": {
                                    "type": "string",
                                    "description": "Parent agent ID for add operations"
                                },
                                "agent": {
                                    "type": "object",
                                    "description": "Agent definition for add/update",
                                    "properties": {
                                        "id": {"type": "string"},
                                        "name": {"type": "string"},
                                        "description": {"type": "string"},
                                        "type": {"type": "string"},
                                        "system_prompt": {"type": "string"},
                                        "routing_strategy": {"type": "string"},
                                        "tools": {
                                            "type": "array",
                                            "items": {"type": "string"}
                                        },
                                        "model": {"type": "string"},
                                        "temperature": {"type": "number"}
                                    }
                                }
                            },
                            "required": ["operation"]
                        }
                    }
                },
                "required": ["workflow_id", "description", "operations"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_workflow_summary",
            "description": "Get the current structure and details of a workflow. Use this to review what has been created.",
            "parameters": {
                "type": "object",
                "properties": {
                    "workflow_id": {
                        "type": "string",
                        "description": "The workflow ID to summarize"
                    }
                },
                "required": ["workflow_id"]
            }
        }
    }
]


class CopilotTools:
    """
    Implements the tools available to the Copilot LLM.

    Handles workflow generation, modification, and inspection.
    """

    def __init__(self, workflow_manager: WorkflowManager):
        self.workflow_manager = workflow_manager

    async def execute_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        session: CopilotSession,
    ) -> Dict[str, Any]:
        """
        Execute a tool by name.

        Args:
            tool_name: Name of the tool to execute
            arguments: Tool arguments
            session: Current copilot session

        Returns:
            Tool execution result
        """
        if tool_name == "generate_workflow":
            return await self.generate_workflow(arguments, session)
        elif tool_name == "patch_workflow":
            return await self.patch_workflow(arguments, session)
        elif tool_name == "get_workflow_summary":
            return await self.get_workflow_summary(arguments, session)
        else:
            return {"error": f"Unknown tool: {tool_name}"}

    async def generate_workflow(
        self,
        args: Dict[str, Any],
        session: CopilotSession,
    ) -> Dict[str, Any]:
        """
        Generate a complete workflow from a plan.

        Args:
            args: Plan arguments with title, description, agents
            session: Current copilot session

        Returns:
            Result with workflow_id and agent details
        """
        try:
            plan = WorkflowPlan(
                title=args["title"],
                description=args["description"],
                agents=[AgentPlanTask(**a) for a in args["agents"]],
            )

            # Create the workflow
            workflow = await self.workflow_manager.create_workflow(
                name=plan.title,
                description=plan.description,
            )

            # Map plan IDs to real agent IDs
            agent_id_map: Dict[str, str] = {}
            created_agents = []

            # Sort agents: root first (no parent), then children
            root_agents = [a for a in plan.agents if not a.parent_id]
            child_agents = [a for a in plan.agents if a.parent_id]

            # Create root agents first
            for agent_plan in root_agents:
                node = self._create_agent_node(agent_plan, None)
                workflow.add_agent(node, None)
                agent_id_map[agent_plan.id] = node.id
                created_agents.append({
                    "plan_id": agent_plan.id,
                    "real_id": node.id,
                    "name": agent_plan.name,
                })

            # Create child agents (may need multiple passes for deep nesting)
            remaining = list(child_agents)
            max_passes = 10
            pass_count = 0

            while remaining and pass_count < max_passes:
                pass_count += 1
                next_remaining = []

                for agent_plan in remaining:
                    real_parent_id = agent_id_map.get(agent_plan.parent_id)
                    if real_parent_id is None:
                        next_remaining.append(agent_plan)
                        continue

                    node = self._create_agent_node(agent_plan, real_parent_id)
                    workflow.add_agent(node, real_parent_id)
                    agent_id_map[agent_plan.id] = node.id
                    created_agents.append({
                        "plan_id": agent_plan.id,
                        "real_id": node.id,
                        "name": agent_plan.name,
                    })

                remaining = next_remaining

            # Update session with workflow ID
            session.workflow_id = workflow.id

            # Persist
            await self.workflow_manager.save_current_state(workflow.id)

            result = {
                "status": "success",
                "workflow_id": workflow.id,
                "name": plan.title,
                "agent_count": len(created_agents),
                "agents": created_agents,
            }

            logger.info(
                f"Generated workflow {workflow.id} with {len(created_agents)} agents"
            )
            return result

        except Exception as e:
            logger.error(f"Error generating workflow: {e}")
            return {"status": "error", "error": str(e)}

    async def patch_workflow(
        self,
        args: Dict[str, Any],
        session: CopilotSession,
    ) -> Dict[str, Any]:
        """
        Modify an existing workflow.

        Args:
            args: Patch arguments with workflow_id, operations
            session: Current copilot session

        Returns:
            Result with applied changes
        """
        try:
            workflow_id = args["workflow_id"]
            workflow = await self.workflow_manager.get_workflow(workflow_id)

            if not workflow:
                return {"status": "error", "error": f"Workflow not found: {workflow_id}"}

            applied_ops = []

            for op_data in args.get("operations", []):
                operation = op_data["operation"]

                if operation == "add":
                    agent_data = op_data.get("agent", {})
                    parent_id = op_data.get("parent_id")
                    agent_plan = AgentPlanTask(
                        id=agent_data.get("id", "new-agent"),
                        name=agent_data.get("name", "New Agent"),
                        description=agent_data.get("description", ""),
                        type=agent_data.get("type", "builtin"),
                        system_prompt=agent_data.get("system_prompt"),
                        routing_strategy=agent_data.get("routing_strategy", "sequential"),
                        tools=agent_data.get("tools", []),
                        model=agent_data.get("model", "gpt-4"),
                        temperature=agent_data.get("temperature", 0.7),
                    )
                    node = self._create_agent_node(agent_plan, parent_id)
                    workflow.add_agent(node, parent_id)
                    applied_ops.append({
                        "operation": "add",
                        "agent_id": node.id,
                        "name": node.name,
                    })

                elif operation == "update":
                    agent_id = op_data.get("agent_id")
                    if not agent_id:
                        continue

                    node = workflow.get_agent(agent_id)
                    if not node:
                        applied_ops.append({
                            "operation": "update",
                            "agent_id": agent_id,
                            "error": "Agent not found",
                        })
                        continue

                    agent_data = op_data.get("agent", {})
                    if "name" in agent_data:
                        node.name = agent_data["name"]
                    if "description" in agent_data:
                        node.description = agent_data["description"]
                    if "routing_strategy" in agent_data:
                        node.routing_strategy = RoutingStrategy(agent_data["routing_strategy"])
                    if "system_prompt" in agent_data and node.config and node.config.builtin_definition:
                        node.config.builtin_definition.system_prompt = agent_data["system_prompt"]
                    if "tools" in agent_data and node.config and node.config.builtin_definition:
                        node.config.builtin_definition.system_tools = agent_data["tools"]

                    applied_ops.append({
                        "operation": "update",
                        "agent_id": agent_id,
                        "name": node.name,
                    })

                elif operation == "delete":
                    agent_id = op_data.get("agent_id")
                    if agent_id:
                        removed = workflow.remove_agent(agent_id)
                        applied_ops.append({
                            "operation": "delete",
                            "agent_id": agent_id,
                            "success": removed is not None,
                        })

            # Persist
            await self.workflow_manager.save_current_state(workflow_id)

            return {
                "status": "success",
                "workflow_id": workflow_id,
                "operations_applied": applied_ops,
            }

        except Exception as e:
            logger.error(f"Error patching workflow: {e}")
            return {"status": "error", "error": str(e)}

    async def get_workflow_summary(
        self,
        args: Dict[str, Any],
        session: CopilotSession,
    ) -> Dict[str, Any]:
        """
        Get a summary of a workflow's structure.

        Args:
            args: Arguments with workflow_id
            session: Current copilot session

        Returns:
            Workflow summary with agent tree structure
        """
        try:
            workflow_id = args["workflow_id"]
            workflow = await self.workflow_manager.get_workflow(workflow_id)

            if not workflow:
                return {"status": "error", "error": f"Workflow not found: {workflow_id}"}

            agents = []
            for node in workflow.tree:
                agent_info = {
                    "id": node.id,
                    "name": node.name,
                    "description": node.description,
                    "type": node.type.value,
                    "parent_id": node.parent_id,
                    "children": node.children,
                    "routing_strategy": node.routing_strategy.value,
                    "enabled": node.enabled,
                }

                # Include system prompt summary if available
                if (node.config and node.config.builtin_definition
                        and node.config.builtin_definition.system_prompt):
                    prompt = node.config.builtin_definition.system_prompt
                    agent_info["system_prompt_preview"] = (
                        prompt[:200] + "..." if len(prompt) > 200 else prompt
                    )

                agents.append(agent_info)

            return {
                "status": "success",
                "workflow_id": workflow_id,
                "name": workflow.name,
                "description": workflow.description,
                "state": workflow.state.value,
                "agent_count": len(agents),
                "agents": agents,
            }

        except Exception as e:
            logger.error(f"Error getting workflow summary: {e}")
            return {"status": "error", "error": str(e)}

    def _create_agent_node(
        self,
        plan: AgentPlanTask,
        parent_id: Optional[str],
    ) -> AgentNode:
        """
        Create an AgentNode from a plan task.

        Args:
            plan: The agent plan
            parent_id: Real parent agent ID

        Returns:
            Configured AgentNode
        """
        # Build builtin definition from plan
        builtin_def = BuiltinAgentDefinition(
            name=plan.name,
            description=plan.description,
            model=plan.model,
            temperature=plan.temperature,
            system_prompt=plan.system_prompt or "",
            system_tools=plan.tools,
            output_format=OutputFormat(format_type="markdown"),
        )

        config = AgentConfig(
            model=plan.model,
            temperature=plan.temperature,
            builtin_definition=builtin_def,
        )

        node = AgentNode(
            name=plan.name,
            description=plan.description,
            type=AgentType(plan.type) if plan.type != "builtin" else AgentType.BUILTIN,
            config=config,
            parent_id=parent_id,
            routing_strategy=RoutingStrategy(plan.routing_strategy),
            routing_conditions=plan.routing_conditions,
        )

        return node
