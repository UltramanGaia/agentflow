from __future__ import annotations

from pathlib import Path

from agentflow.agents.base import AgentAdapter
from agentflow.env import merge_env_layers
from agentflow.prepared import ExecutionPaths, PreparedExecution
from agentflow.specs import NodeSpec, RepoInstructionsMode, ToolAccess


_CLAUDE_READ_ONLY_TOOLS = [
    "Read",
    "Glob",
    "Grep",
    "LS",
    "NotebookRead",
    "Task",
    "TaskOutput",
    "TodoRead",
    "WebFetch",
    "WebSearch",
]

_CLAUDE_READ_WRITE_TOOLS = _CLAUDE_READ_ONLY_TOOLS + [
    "Write",
    "Edit",
    "MultiEdit",
    "NotebookEdit",
    "TodoWrite",
    "Bash",
]


class ClaudeAdapter(AgentAdapter):
    def prepare(self, node: NodeSpec, prompt: str, paths: ExecutionPaths) -> PreparedExecution:
        executable = node.executable or "claude"
        repo_instructions_ignored = node.repo_instructions_mode == RepoInstructionsMode.IGNORE
        command = [
            executable,
            "-p",
            prompt,
            "--output-format",
            "stream-json",
            "--verbose",
            "--permission-mode",
            "bypassPermissions",
        ]
        if repo_instructions_ignored:
            command.extend(["--bare", "--add-dir", paths.target_workdir])
        if node.model:
            command.extend(["--model", node.model])
        allowed_tools = _CLAUDE_READ_ONLY_TOOLS if node.tools == ToolAccess.READ_ONLY else _CLAUDE_READ_WRITE_TOOLS
        command.extend(["--tools", ",".join(allowed_tools)])
        env = merge_env_layers(node.env)
        command.extend(node.extra_args)
        cwd = paths.target_workdir
        if repo_instructions_ignored:
            cwd = str(Path(paths.target_runtime_dir))
        return PreparedExecution(
            command=command,
            env=env,
            cwd=cwd,
            trace_kind="claude",
        )
