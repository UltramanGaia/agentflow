"""Adapters for local utility nodes: python and shell."""

from __future__ import annotations

from agentflow.prepared import ExecutionPaths, PreparedExecution
from agentflow.specs import NodeSpec


class PythonAdapter:
    """Run a Python script. The prompt is the Python code."""

    def prepare(self, node: NodeSpec, prompt: str, paths: ExecutionPaths) -> PreparedExecution:
        return PreparedExecution(
            command=["python3", "-c", prompt],
            env=dict(node.env or {}),
            cwd=str(paths.host_workdir),
            trace_kind="python",
            runtime_files={},
            stdin=None,
        )


class ShellAdapter:
    """Run a shell command. The prompt is the bash script."""

    def prepare(self, node: NodeSpec, prompt: str, paths: ExecutionPaths) -> PreparedExecution:
        return PreparedExecution(
            command=["bash", "-c", prompt],
            env=dict(node.env or {}),
            cwd=str(paths.host_workdir),
            trace_kind="shell",
            runtime_files={},
            stdin=None,
        )
