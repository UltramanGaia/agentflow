from __future__ import annotations

from agentflow.launch_artifacts import launch_artifact_payload, sanitize_launch_value
from agentflow.runner import LaunchPlan


def test_sanitize_launch_value_redacts_sensitive_nested_values() -> None:
    payload = sanitize_launch_value(
        "payload",
        {
            "api_key": "secret",
            "nested": {"token": "hidden", "visible": "ok"},
            "items": [{"password": "hidden"}, "plain"],
        },
    )

    assert payload == {
        "api_key": "<redacted>",
        "nested": {"token": "<redacted>", "visible": "ok"},
        "items": [{"password": "<redacted>"}, "plain"],
    }


def test_launch_artifact_payload_redacts_command_and_env() -> None:
    plan = LaunchPlan(
        kind="process",
        command=["agent", "API_KEY=secret", "--flag"],
        env={"SAFE": "1", "API_KEY": "secret"},
        cwd="/workspace",
        stdin="input",
        runtime_files=["b.txt", "a.txt"],
        payload={"token": "hidden", "value": 3},
    )

    payload = launch_artifact_payload(2, plan)

    assert payload["attempt"] == 2
    assert payload["command"] == ["agent", "API_KEY=<redacted>", "--flag"]
    assert payload["env"] == {"SAFE": "1", "API_KEY": "<redacted>"}
    assert payload["runtime_files"] == ["b.txt", "a.txt"]
    assert payload["payload"] == {"token": "<redacted>", "value": 3}
