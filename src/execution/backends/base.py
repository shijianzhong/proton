import abc
from dataclasses import dataclass
from typing import Dict, Any, Optional

@dataclass
class RunResult:
    output: str
    error: Optional[str] = None
    exit_code: int = 0

class ExecutionBackend(abc.ABC):
    """Base class for execution backends."""
    @abc.abstractmethod
    async def run_python(self, code: str, params: Dict[str, Any], timeout: int = 30) -> RunResult:
        pass
