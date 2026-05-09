from __future__ import annotations

from agentflow.agents.base import AgentAdapter
from agentflow.prepared import ExecutionPaths, PreparedExecution
from agentflow.specs import NodeSpec, RepoInstructionsMode, ToolAccess


class CodexAdapter(AgentAdapter):
    def _resolve_sandbox_mode(self, node: NodeSpec) -> str:
        return "read-only" if node.tools == ToolAccess.READ_ONLY else "workspace-write"

    def prepare(self, node: NodeSpec, prompt: str, paths: ExecutionPaths) -> PreparedExecution:
        executable = node.executable or "codex"
        sandbox = self._resolve_sandbox_mode(node)
        repo_instructions_ignored = node.repo_instructions_mode == RepoInstructionsMode.IGNORE
        command = [
            executable,
            "exec",
            "--json",
            "--skip-git-repo-check",
            "-c",
            'approval_policy="never"',
            "-c",
            "suppress_unstable_features_warning=true",
            "--sandbox",
            sandbox,
        ]
        if node.model:
            command.extend(["--model", node.model])
        if repo_instructions_ignored:
            command.extend(["--disable", "plugins"])
            command.extend(["--add-dir", paths.target_workdir])
        command.extend(node.extra_args)
        command.append(prompt)

        cwd = paths.target_workdir
        if repo_instructions_ignored:
            from pathlib import Path

            cwd = str(Path(paths.target_runtime_dir))
        return PreparedExecution(
            command=command,
            env={},
            cwd=cwd,
            trace_kind="codex",
        )
