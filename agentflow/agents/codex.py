from __future__ import annotations

from agentflow.agents.base import AgentAdapter
from agentflow.env import merge_env_layers
from agentflow.prepared import ExecutionPaths, PreparedExecution
from agentflow.specs import NodeSpec, RepoInstructionsMode, ToolAccess


class CodexAdapter(AgentAdapter):
    _SUPPORTED_SANDBOX_MODES = {"read-only", "workspace-write", "danger-full-access"}

    def _resolve_sandbox_mode(self, node: NodeSpec, env: dict[str, str]) -> str:
        override = (env.pop("AGENTFLOW_CODEX_SANDBOX_MODE", "") or "").strip()
        if not override:
            return "read-only" if node.tools == ToolAccess.READ_ONLY else "workspace-write"
        if override not in self._SUPPORTED_SANDBOX_MODES:
            raise ValueError(
                "AGENTFLOW_CODEX_SANDBOX_MODE must be one of: "
                + ", ".join(sorted(self._SUPPORTED_SANDBOX_MODES))
            )
        return override

    def prepare(self, node: NodeSpec, prompt: str, paths: ExecutionPaths) -> PreparedExecution:
        provider = self.provider_config(node.provider, node.agent)
        executable = node.executable or "codex"
        env = merge_env_layers(node.env)
        sandbox = self._resolve_sandbox_mode(node, env)
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
        if provider:
            command.extend(["--profile", provider.name])
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
            env=env,
            cwd=cwd,
            trace_kind="codex",
        )
