from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from agentflow.periodic import PeriodicActionEnvelope
from agentflow.periodic_scheduler import PeriodicScheduler
from agentflow.specs import AgentKind, NodeResult, NodeRuntimeState, NodeSpec, NodeStatus, PipelineSpec, RunRecord
from agentflow.store import RunStore


def _pipeline(tmp_path: Path) -> PipelineSpec:
    return PipelineSpec(
        name="periodic-scheduler",
        working_dir=str(tmp_path),
        nodes=[
            NodeSpec(id="controller", agent=AgentKind.SHELL, prompt="watch"),
            NodeSpec(id="worker", agent=AgentKind.SHELL, prompt="work"),
            NodeSpec(id="done", agent=AgentKind.SHELL, prompt="done"),
        ],
        fanouts={"workers": ["worker", "done"]},
    )


def test_periodic_scheduler_detects_settled_fanout(tmp_path: Path) -> None:
    pipeline = _pipeline(tmp_path)
    results = {
        "worker": NodeResult(node_id="worker", status=NodeStatus.COMPLETED),
        "done": NodeResult(node_id="done", status=NodeStatus.FAILED),
    }

    scheduler = PeriodicScheduler(
        store=RunStore(tmp_path / "runs"),
        publish=lambda *args, **kwargs: None,
        node_runtime_state=lambda run_id, node_id: NodeRuntimeState(),
        request_node_cancel=lambda run_id, node_id: None,
        queue_node_rerun=lambda run_id, node_id: None,
    )

    assert scheduler.fanout_group_settled(pipeline, results, "workers")


def test_periodic_scheduler_applies_cancel_and_rerun_actions(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "runs")
    pipeline = _pipeline(tmp_path)
    record = RunRecord(
        id="run",
        pipeline=pipeline,
        nodes={
            "controller": NodeResult(node_id="controller", status=NodeStatus.READY),
            "worker": NodeResult(node_id="worker", status=NodeStatus.RUNNING),
            "done": NodeResult(node_id="done", status=NodeStatus.COMPLETED),
        },
    )
    asyncio.run(store.create_run(record))
    published: list[tuple[str, dict[str, Any]]] = []
    cancelled: list[str] = []
    reruns: list[str] = []
    runtime_states: dict[str, NodeRuntimeState] = {}

    async def publish(run_id: str, event_type: str, **data: Any) -> None:
        published.append((event_type, data))

    scheduler = PeriodicScheduler(
        store=store,
        publish=publish,
        node_runtime_state=lambda run_id, node_id: runtime_states.setdefault(node_id, NodeRuntimeState()),
        request_node_cancel=lambda run_id, node_id: cancelled.append(node_id),
        queue_node_rerun=lambda run_id, node_id: reruns.append(node_id),
    )
    actions = PeriodicActionEnvelope.model_validate(
        {
            "actions": [
                {"kind": "cancel", "node_ids": ["worker"], "reason": "stop"},
                {"kind": "rerun", "node_ids": ["done"], "reason": "again"},
            ]
        }
    )
    remaining: set[str] = set()

    asyncio.run(
        scheduler.apply_actions(
            "run",
            "controller",
            watched_group="workers",
            actions=actions,
            remaining=remaining,
            in_progress={},
        )
    )

    assert cancelled == ["worker"]
    assert reruns == ["done"]
    assert remaining == {"done"}
    assert store.get_run("run").nodes["done"].status == NodeStatus.PENDING
    assert published[0][0] == "node_control_actions_applied"
