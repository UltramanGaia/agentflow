from __future__ import annotations

from agentflow.agents.base import AgentAdapter
from agentflow.prepared import ExecutionPaths, PreparedExecution
from agentflow.specs import NodeSpec


class PythonAdapter(AgentAdapter):
    """Run a Python script. The prompt is the Python code."""

    def prepare(self, node: NodeSpec, prompt: str, paths: ExecutionPaths) -> PreparedExecution:
        return PreparedExecution(
            command=["python3", "-c", prompt],
            env={},
            cwd=str(paths.host_workdir),
            trace_kind="python",
            runtime_files={},
            stdin=None,
        )
