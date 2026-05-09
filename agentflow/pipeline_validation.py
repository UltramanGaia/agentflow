from __future__ import annotations

from agentflow.specs_core import LocalTarget
from agentflow.specs_models import PipelineSpec


def validate_pipeline_runtime_config(pipeline: PipelineSpec) -> PipelineSpec:
    """Validate execution-specific pipeline settings outside the pure specs model."""

    if pipeline.local_target_defaults is not None:
        validate_local_target_runtime(pipeline.local_target_defaults, subject="local_target_defaults")
    for node in pipeline.nodes:
        validate_local_target_runtime(node.target, subject=f"nodes.{node.id}.target")
    return pipeline


def validate_local_target_runtime(target: LocalTarget, *, subject: str) -> LocalTarget:
    unsupported_fields: list[str] = []
    if target.shell and target.shell.strip():
        unsupported_fields.append("shell")
    if target.shell_login:
        unsupported_fields.append("shell_login")
    if target.shell_interactive:
        unsupported_fields.append("shell_interactive")
    if unsupported_fields:
        joined = ", ".join(f"`{subject}.{field}`" for field in unsupported_fields)
        raise ValueError(f"{joined} are no longer supported; local execution always uses `/bin/bash -c`")
    return target
