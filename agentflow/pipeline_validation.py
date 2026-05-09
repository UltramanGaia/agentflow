from __future__ import annotations

from agentflow.local_shell import invalid_bash_long_option_error, shell_wrapper_requires_command_placeholder
from agentflow.specs import LocalTarget, PipelineSpec


_SHELL_COMMAND_PLACEHOLDER_MESSAGE = (
    "`target.shell` already includes a shell command payload. Add `{command}` where AgentFlow should "
    "inject the prepared agent command."
)


def validate_pipeline_runtime_config(pipeline: PipelineSpec) -> PipelineSpec:
    """Validate execution-specific pipeline settings outside the pure specs model."""

    if pipeline.local_target_defaults is not None:
        validate_local_target_shell(pipeline.local_target_defaults, subject="local_target_defaults")
    for node in pipeline.nodes:
        validate_local_target_shell(node.target, subject=f"nodes.{node.id}.target")
    return pipeline


def validate_local_target_shell(target: LocalTarget, *, subject: str = "target") -> LocalTarget:
    shell = target.shell
    if not shell or not shell.strip():
        return target

    invalid_option_error = invalid_bash_long_option_error(shell)
    if invalid_option_error is not None:
        raise ValueError(f"`{subject}.shell` uses an unsupported bash long option. {invalid_option_error}")
    if shell_wrapper_requires_command_placeholder(shell):
        raise ValueError(_SHELL_COMMAND_PLACEHOLDER_MESSAGE.replace("`target.shell`", f"`{subject}.shell`"))
    return target
