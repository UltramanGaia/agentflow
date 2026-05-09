from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Callable

import pytest

from agentflow.orchestrator import Orchestrator
from agentflow.specs import AgentKind, NodeResult, NodeSpec, NodeStatus, PipelineSpec, RunRecord, RunStatus
from agentflow.store import RunStore


def test_resume_reuses_start_background(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pipeline = PipelineSpec(
        name="resume-test",
        working_dir=str(tmp_path),
        nodes=[NodeSpec(id="node", agent=AgentKind.SHELL, prompt="run")],
    )
    old_run = RunRecord(
        id="old",
        status=RunStatus.FAILED,
        pipeline=pipeline,
        nodes={"node": NodeResult(node_id="node", status=NodeStatus.FAILED)},
    )
    store = RunStore(tmp_path / "runs")
    asyncio.run(store.create_run(old_run))

    orchestrator = Orchestrator(store=store)
    started: dict[str, Any] = {}

    def fake_start_background(self: Orchestrator, run_id: str, entrypoint: Callable[[], Any]) -> None:
        started["run_id"] = run_id
        started["entrypoint"] = entrypoint

    monkeypatch.setattr(Orchestrator, "_start_background", fake_start_background)

    new_run = asyncio.run(orchestrator.resume("old"))

    assert started["run_id"] == new_run.id
    assert callable(started["entrypoint"])
    assert new_run.id in orchestrator._run_finished
