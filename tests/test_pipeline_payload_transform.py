from __future__ import annotations

from agentflow.loader import load_pipeline_from_data
from agentflow.specs import AgentKind, PipelineSpec, prepare_pipeline_payload


def _pipeline_payload() -> dict[str, object]:
    return {
        "name": "defaults",
        "local_target_defaults": {"cwd": "workspace", "shell_init": "export GLOBAL_INIT=1"},
        "node_defaults": {"tools": "read_write"},
        "nodes": [
            {
                "id": "node",
                "agent": "shell",
                "prompt": "run",
            }
        ],
    }


def test_loader_applies_pipeline_payload_transformations() -> None:
    pipeline = load_pipeline_from_data(_pipeline_payload())
    node = pipeline.nodes[0]

    assert node.agent == AgentKind.SHELL
    assert node.tools == "read_write"
    assert node.target.cwd == "workspace"
    assert node.target.shell_init == "export GLOBAL_INIT=1"


def test_pipeline_spec_validation_does_not_implicitly_transform_payloads() -> None:
    pipeline = PipelineSpec.model_validate(_pipeline_payload())
    node = pipeline.nodes[0]

    assert node.target.cwd is None
    assert node.target.shell is None
    assert node.target.shell_init is None


def test_prepare_pipeline_payload_is_the_explicit_transformation_boundary() -> None:
    prepared = prepare_pipeline_payload(_pipeline_payload())
    pipeline = PipelineSpec.model_validate(prepared)
    node = pipeline.nodes[0]

    assert node.target.cwd == "workspace"
    assert node.target.shell_init == "export GLOBAL_INIT=1"
