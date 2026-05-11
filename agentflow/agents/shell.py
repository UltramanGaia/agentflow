from __future__ import annotations

from agentflow.agents.base import AgentAdapter
from agentflow.prepared import ExecutionPaths, PreparedExecution
from agentflow.specs import NodeSpec


class ShellAdapter(AgentAdapter):
    """Run a shell command. The prompt is the bash script."""

    def prepare(self, node: NodeSpec, prompt: str, paths: ExecutionPaths) -> PreparedExecution:
        return PreparedExecution(
            command=["bash", "-c", prompt],
            env={},
            cwd=str(paths.host_workdir),
            trace_kind="shell",
            runtime_files={},
            stdin=None,
        )
