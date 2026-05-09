from __future__ import annotations

import pytest
from pydantic import ValidationError

from agentflow.loader import load_pipeline_from_data
from agentflow.specs import LocalTarget, PipelineSpec


def _pipeline_with_shell(shell: str) -> dict[str, object]:
    return {
        "name": "shell-validation",
        "nodes": [
            {
                "id": "node",
                "agent": "shell",
                "prompt": "run",
                "target": {"kind": "local", "shell": shell},
            }
        ],
    }


def test_specs_reject_target_shell_runtime_config() -> None:
    with pytest.raises(ValidationError):
        PipelineSpec.model_validate(_pipeline_with_shell("bash --command echo"))


def test_loader_rejects_target_shell_runtime_config() -> None:
    with pytest.raises(ValidationError):
        load_pipeline_from_data(_pipeline_with_shell("bash --command echo"))


def test_local_target_allows_shell_init_without_shell() -> None:
    target = LocalTarget(shell_init="source ~/.bashrc")

    assert target.shell_init == "source ~/.bashrc"
    assert "shell" not in type(target).model_fields


def test_local_target_rejects_shell_flags() -> None:
    with pytest.raises(ValidationError):
        LocalTarget.model_validate({"shell_login": True})
