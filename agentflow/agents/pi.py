from __future__ import annotations

from pathlib import Path

from agentflow.agents.base import AgentAdapter
from agentflow.prepared import ExecutionPaths, PreparedExecution
from agentflow.specs import NodeSpec, RepoInstructionsMode, ToolAccess


_PI_READ_ONLY_TOOLS = "read,grep,find,ls"
_PI_READ_WRITE_TOOLS = "read,bash,edit,write,grep,find,ls"


class PiAdapter(AgentAdapter):
    def prepare(self, node: NodeSpec, prompt: str, paths: ExecutionPaths) -> PreparedExecution:
        executable = node.executable or "pi"
        repo_instructions_ignored = node.repo_instructions_mode == RepoInstructionsMode.IGNORE

        command: list[str] = [
            executable,
            "--print",
            "--mode",
            "json",
            "--no-session",
        ]

        tools = _PI_READ_ONLY_TOOLS if node.tools == ToolAccess.READ_ONLY else _PI_READ_WRITE_TOOLS
        command.extend(["--tools", tools])

        if node.model:
            command.extend(["--model", node.model])

        if repo_instructions_ignored:
            command.extend(["--no-skills", "--no-extensions", "--no-prompt-templates"])

        command.extend(node.extra_args)

        cwd = paths.target_workdir
        if repo_instructions_ignored:
            cwd = str(Path(paths.target_runtime_dir))

        # Pass the prompt via stdin so it is never parsed as a flag or `@file`
        # reference by Pi's positional-message argument handling.
        return PreparedExecution(
            command=command,
            env={},
            cwd=cwd,
            trace_kind="pi",
            stdin=prompt,
        )
