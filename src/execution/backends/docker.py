import asyncio
import json
import logging
import shutil
from typing import Dict, Any
from .base import ExecutionBackend, RunResult
from .local import LocalProcessBackend

logger = logging.getLogger(__name__)

class DockerBackend(ExecutionBackend):
    """Executes code in a Docker container with strict isolation."""
    
    def __init__(self, image: str = "python:3.11-slim"):
        self.image = image
        self.fallback_backend = LocalProcessBackend()
        self._docker_available = None

    async def _check_docker(self) -> bool:
        if self._docker_available is None:
            self._docker_available = shutil.which("docker") is not None
            if self._docker_available:
                # Double check if docker daemon is running
                try:
                    proc = await asyncio.create_subprocess_exec(
                        "docker", "info",
                        stdout=asyncio.subprocess.DEVNULL,
                        stderr=asyncio.subprocess.DEVNULL
                    )
                    await proc.wait()
                    self._docker_available = (proc.returncode == 0)
                except Exception:
                    self._docker_available = False
        return self._docker_available

    async def run_python(self, code: str, params: Dict[str, Any], timeout: int = 30) -> RunResult:
        if not await self._check_docker():
            logger.warning("Docker is not available or daemon is not running. Falling back to LocalProcessBackend.")
            return await self.fallback_backend.run_python(code, params, timeout)

        wrapper_code = f"""
import sys
import json

try:
    params = json.loads(sys.stdin.read() or "{{}}")
except Exception:
    params = {{}}

result = None
try:
{self._indent(code, 4)}
    print(json.dumps({{"__proton_result": result}}))
except Exception as e:
    import traceback
    print(json.dumps({{"__proton_error": str(e), "traceback": traceback.format_exc()}}), file=sys.stderr)
    sys.exit(1)
"""
        
        cmd = [
            "docker", "run", "--rm", "-i",
            "--net=none", "--memory=256m", "--cpus=1",
            self.image,
            "python", "-c", wrapper_code
        ]

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            input_data = json.dumps(params).encode('utf-8')
            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(input=input_data),
                    timeout=timeout
                )
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                return RunResult(output="", error=f"Execution timed out after {timeout}s", exit_code=124)

            stdout_str = stdout.decode('utf-8').strip()
            stderr_str = stderr.decode('utf-8').strip()
            
            if process.returncode != 0:
                error_msg = stderr_str
                for line in stderr_str.splitlines():
                    try:
                        data = json.loads(line)
                        if "__proton_error" in data:
                            error_msg = data["__proton_error"]
                            break
                    except json.JSONDecodeError:
                        pass
                return RunResult(output="", error=error_msg, exit_code=process.returncode)

            final_result = stdout_str
            for line in reversed(stdout_str.splitlines()):
                try:
                    data = json.loads(line)
                    if "__proton_result" in data:
                        final_result = str(data["__proton_result"])
                        break
                except json.JSONDecodeError:
                    pass

            return RunResult(output=final_result, error=None, exit_code=0)
            
        except Exception as e:
            logger.error(f"Docker backend error: {e}")
            return RunResult(output="", error=str(e), exit_code=-1)

    def _indent(self, text: str, spaces: int) -> str:
        prefix = " " * spaces
        return "\\n".join(prefix + line for line in text.splitlines())
