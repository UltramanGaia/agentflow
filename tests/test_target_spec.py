import pytest
from pydantic import ValidationError

from agentflow.specs_models import NodeSpec


def test_local_target_accepts_current_shape() -> None:
    node = NodeSpec.model_validate(
        {
            "id": "node",
            "agent": "gaia",
            "prompt": "Inspect the repo.",
            "target": {"cwd": "."},
        }
    )

    assert node.target.cwd == "."


def test_local_target_rejects_legacy_kind_field() -> None:
    with pytest.raises(ValidationError):
        NodeSpec.model_validate(
            {
                "id": "node",
                "agent": "gaia",
                "prompt": "Inspect the repo.",
                "target": {"kind": "local", "cwd": "."},
            }
        )
