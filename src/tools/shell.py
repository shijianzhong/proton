"""
Shell execution tool: run commands in a controlled environment.
"""

import asyncio
import logging
import os
import shlex
from typing import Any, List, Optional

from .base import SystemTool, ToolParameterSchema

logger = logging.getLogger(__name__)


# Default workspace directory for shell execution
DEFAULT_WORKSPACE = os.environ.get("PROTON_WORKSPACE", os.path.expanduser("~/.proton/workspace"))

# Maximum command execution time (seconds)
DEFAULT_TIMEOUT = int(os.environ.get("PROTON_SHELL_TIMEOUT", "60"))

# Commands that are blocked for security
BLOCKED_COMMANDS = {
    "rm -rf /",
    "rm -rf /*",
    "mkfs",
    ":(){:|:&};:",  # fork bomb
    "dd if=/dev/zero of=/dev/sda",
    "chmod -R 777 /",
    "> /dev/sda",
}

# Potentially dangerous command prefixes
DANGEROUS_PREFIXES = ["sudo", "su ", "rm -rf", "mkfs", "fdisk", "format"]


class ShellExecTool(SystemTool):
    """Execute shell commands."""

    @property
    def name(self) -> str:
        return "shell_exec"

    @property
    def description(self) -> str:
        return (
            "Execute a shell command and return its output. "
            "Use for tasks like running scripts, installing packages, git operations, etc. "
            "The command runs in the workspace directory."
        )

    @property
    def parameters(self) -> List[ToolParameterSchema]:
        return [
            ToolParameterSchema(
                name="command",
                type="string",
                description="The shell command to execute",
                required=True,
            ),
            ToolParameterSchema(
                name="timeout",
                type="integer",
                description=f"Timeout in seconds (default: {DEFAULT_TIMEOUT}, max: 300)",
                required=False,
                default=DEFAULT_TIMEOUT,
            ),
            ToolParameterSchema(
                name="working_dir",
                type="string",
                description="Working directory (relative to workspace)",
                required=False,
                default=".",
            ),
        ]

    @property
    def category(self) -> str:
        return "shell"

    @property
    def requires_approval(self) -> bool:
        return True

    @property
    def is_dangerous(self) -> bool:
        return True

    def _is_command_safe(self, command: str) -> tuple[bool, str]:
        """Check if a command is safe to execute."""
        cmd_lower = command.lower().strip()

        # Check blocked commands
        for blocked in BLOCKED_COMMANDS:
            if blocked.lower() in cmd_lower:
                return False, f"Blocked command detected: {blocked}"

        # Check dangerous prefixes
        for prefix in DANGEROUS_PREFIXES:
            if cmd_lower.startswith(prefix.lower()):
                return False, f"Potentially dangerous command: {prefix}"

        return True, ""

    async def execute(self, **kwargs: Any) -> str:
        command = kwargs.get("command", "")
        timeout = min(kwargs.get("timeout", DEFAULT_TIMEOUT), 300)  # Max 5 minutes
        working_dir = kwargs.get("working_dir", ".")

        if not command:
            return "Error: command is required"

        # Security check
        is_safe, reason = self._is_command_safe(command)
        if not is_safe:
            return f"Error: Command rejected - {reason}"

        # Resolve working directory
        workspace = os.path.expanduser(DEFAULT_WORKSPACE)
        os.makedirs(workspace, exist_ok=True)

        if os.path.isabs(working_dir):
            cwd = working_dir
        else:
            cwd = os.path.join(workspace, working_dir)

        if not os.path.isdir(cwd):
            return f"Error: Working directory does not exist: {working_dir}"

        try:
            # Execute command
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
                env={**os.environ, "HOME": os.path.expanduser("~")},
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=timeout
                )
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                return f"Error: Command timed out after {timeout} seconds"

            # Decode output
            stdout_str = stdout.decode("utf-8", errors="replace").strip()
            stderr_str = stderr.decode("utf-8", errors="replace").strip()

            # Build result
            result_parts = []

            if process.returncode != 0:
                result_parts.append(f"[Exit code: {process.returncode}]")

            if stdout_str:
                result_parts.append(f"[STDOUT]\n{stdout_str}")

            if stderr_str:
                result_parts.append(f"[STDERR]\n{stderr_str}")

            if not result_parts:
                result_parts.append("Command completed successfully (no output)")

            return "\n\n".join(result_parts)

        except Exception as e:
            logger.error(f"Error executing shell command: {e}")
            return f"Error executing command: {e}"


class ShellExecBackgroundTool(SystemTool):
    """Execute a shell command in the background."""

    @property
    def name(self) -> str:
        return "shell_exec_background"

    @property
    def description(self) -> str:
        return (
            "Execute a shell command in the background. "
            "Useful for long-running processes. Returns immediately with a process ID. "
            "Note: Output is not captured for background processes."
        )

    @property
    def parameters(self) -> List[ToolParameterSchema]:
        return [
            ToolParameterSchema(
                name="command",
                type="string",
                description="The shell command to execute in background",
                required=True,
            ),
            ToolParameterSchema(
                name="working_dir",
                type="string",
                description="Working directory (relative to workspace)",
                required=False,
                default=".",
            ),
        ]

    @property
    def category(self) -> str:
        return "shell"

    @property
    def requires_approval(self) -> bool:
        return True

    @property
    def is_dangerous(self) -> bool:
        return True

    async def execute(self, **kwargs: Any) -> str:
        command = kwargs.get("command", "")
        working_dir = kwargs.get("working_dir", ".")

        if not command:
            return "Error: command is required"

        # Resolve working directory
        workspace = os.path.expanduser(DEFAULT_WORKSPACE)
        os.makedirs(workspace, exist_ok=True)

        if os.path.isabs(working_dir):
            cwd = working_dir
        else:
            cwd = os.path.join(workspace, working_dir)

        if not os.path.isdir(cwd):
            return f"Error: Working directory does not exist: {working_dir}"

        try:
            # Start process in background
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
                cwd=cwd,
                start_new_session=True,  # Detach from parent
            )

            return f"Background process started with PID: {process.pid}"

        except Exception as e:
            logger.error(f"Error starting background process: {e}")
            return f"Error starting background process: {e}"
