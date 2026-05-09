from __future__ import annotations

from pathlib import Path

from agentflow.agents.base import AgentAdapter
from agentflow.env import merge_env_layers
from agentflow.prepared import ExecutionPaths, PreparedExecution
from agentflow.specs import NodeSpec, RepoInstructionsMode


class GaiaAdapter(AgentAdapter):
    def prepare(self, node: NodeSpec, prompt: str, paths: ExecutionPaths) -> PreparedExecution:
        executable = node.executable or "gaia"
        env = merge_env_layers(node.env)
        repo_instructions_ignored = node.repo_instructions_mode == RepoInstructionsMode.IGNORE

        command = [
            executable,
            "run",
            "--format",
            "json",
            "--dir",
            paths.target_workdir,
        ]
        if node.model:
            command.extend(["--model", node.model])

        command.extend(node.extra_args)
        command.extend(["--", prompt])

        cwd = paths.target_workdir
        if repo_instructions_ignored:
            cwd = str(Path(paths.target_runtime_dir))

        return PreparedExecution(
            command=command,
            env=env,
            cwd=cwd,
            trace_kind="gaia",
        )
