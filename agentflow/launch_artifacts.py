from __future__ import annotations

from agentflow.runner import LaunchPlan


def launch_artifact_payload(attempt_number: int, plan: LaunchPlan) -> dict[str, Any]:
    return {
        "attempt": attempt_number,
        "kind": plan.kind,
        "command": list(plan.command) if plan.command is not None else None,
        "env": plan.env,
        "cwd": plan.cwd,
        "stdin": plan.stdin,
        "runtime_files": list(plan.runtime_files),
        "payload": plan.payload,
    }
