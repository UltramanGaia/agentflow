from __future__ import annotations

from agentflow.graph_optimizer import optimizer_failure_summary


def test_optimizer_failure_summary_includes_exit_and_streams() -> None:
    summary = optimizer_failure_summary(
        "Optimizer",
        exit_code=2,
        stdout="out",
        stderr="err",
    )

    assert summary == "Optimizer exited with code 2.\n\nstdout:\nout\n\nstderr:\nerr"


def test_optimizer_failure_summary_prefers_explicit_error() -> None:
    summary = optimizer_failure_summary("Pipeline", error="failed to load")

    assert summary == "failed to load"
