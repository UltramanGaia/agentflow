from __future__ import annotations

from typing import Any

from agentflow.runner import LaunchPlan
from agentflow.utils import looks_sensitive_key, redact_sensitive_shell_value


def sanitize_launch_value(key: str | None, value: Any) -> Any:
    if key and looks_sensitive_key(key) and value is not None:
        return "<redacted>"
    if isinstance(value, dict):
        if key == "runtime_files":
            return sorted(value)
        return {
            inner_key: sanitize_launch_value(inner_key, inner_value)
            for inner_key, inner_value in value.items()
        }
    if isinstance(value, list):
        return [sanitize_launch_value(None, item) for item in value]
    return value


def launch_artifact_payload(attempt_number: int, plan: LaunchPlan) -> dict[str, Any]:
    return {
        "attempt": attempt_number,
        "kind": plan.kind,
        "command": redact_sensitive_shell_value(list(plan.command)) if plan.command is not None else None,
        "env": sanitize_launch_value("env", plan.env),
        "cwd": plan.cwd,
        "stdin": plan.stdin,
        "runtime_files": list(plan.runtime_files),
        "payload": sanitize_launch_value("payload", plan.payload),
    }
