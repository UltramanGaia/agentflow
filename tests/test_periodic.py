from __future__ import annotations

from agentflow.periodic import PeriodicActionEnvelope, normalize_periodic_output_text, parse_periodic_actions


def test_normalize_periodic_output_text_strips_json_fence() -> None:
    assert normalize_periodic_output_text("```json\n{\"actions\": []}\n```") == '{"actions": []}'


def test_parse_periodic_actions_accepts_empty_output() -> None:
    envelope, error = parse_periodic_actions("")

    assert envelope == PeriodicActionEnvelope()
    assert error is None


def test_parse_periodic_actions_reports_invalid_json() -> None:
    envelope, error = parse_periodic_actions("{not json")

    assert envelope is None
    assert error is not None
    assert "invalid JSON control envelope" in error


def test_parse_periodic_actions_validates_envelope() -> None:
    envelope, error = parse_periodic_actions(
        '{"analysis": "watching", "actions": [{"kind": "cancel", "node_ids": ["worker"], "reason": "done"}]}'
    )

    assert error is None
    assert envelope is not None
    assert envelope.analysis == "watching"
    assert envelope.actions[0].kind == "cancel"
    assert envelope.actions[0].node_ids == ["worker"]
