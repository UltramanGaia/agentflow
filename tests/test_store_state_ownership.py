from __future__ import annotations

import asyncio
import json
from pathlib import Path

from agentflow.specs import AgentKind, NodeResult, NodeSpec, NodeStatus, PipelineSpec, RunRecord, RunStatus
from agentflow.store import RunStore


def _record(run_id: str, tmp_path: Path, *, status: RunStatus = RunStatus.QUEUED) -> RunRecord:
    pipeline = PipelineSpec(
        name="state-ownership",
        working_dir=str(tmp_path),
        nodes=[NodeSpec(id="node", agent=AgentKind.SHELL, prompt="run")],
    )
    return RunRecord(
        id=run_id,
        status=status,
        pipeline=pipeline,
        nodes={"node": NodeResult(node_id="node", status=NodeStatus.PENDING)},
    )


def test_run_store_uses_memory_as_runtime_source_of_truth(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "runs")
    record = _record("run", tmp_path)
    asyncio.run(store.create_run(record))

    run_path = tmp_path / "runs" / "run" / "run.json"
    disk_payload = json.loads(run_path.read_text(encoding="utf-8"))
    disk_payload["status"] = RunStatus.COMPLETED.value
    run_path.write_text(json.dumps(disk_payload), encoding="utf-8")

    assert store.get_run("run").status == RunStatus.QUEUED
    assert store.list_runs()[0].status == RunStatus.QUEUED


def test_new_run_store_instance_restores_from_disk(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "runs")
    asyncio.run(store.create_run(_record("run", tmp_path, status=RunStatus.COMPLETED)))

    restored = RunStore(tmp_path / "runs")

    assert restored.get_run("run").status == RunStatus.COMPLETED
