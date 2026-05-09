from __future__ import annotations

import pytest

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


def test_specs_do_not_depend_on_shell_runtime_validation() -> None:
    pipeline = PipelineSpec.model_validate(_pipeline_with_shell("bash --command echo"))

    assert pipeline.nodes[0].target.shell == "bash --command echo"


def test_loader_validates_runtime_shell_config() -> None:
    with pytest.raises(ValueError, match="unsupported bash long option"):
        load_pipeline_from_data(_pipeline_with_shell("bash --command echo"))


def test_local_target_keeps_structural_shell_validation() -> None:
    with pytest.raises(ValueError, match="require `target.shell`"):
        LocalTarget(shell_init="source ~/.bashrc")
