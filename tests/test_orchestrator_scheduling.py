from __future__ import annotations

import asyncio
from pathlib import Path

from agentflow.agents.base import AgentAdapter
from agentflow.orchestrator import Orchestrator
from agentflow.prepared import ExecutionPaths, PreparedExecution
from agentflow.runner import LaunchPlan, RawExecutionResult, Runner
from agentflow.specs import AgentKind, NodeResult, NodeSpec, NodeStatus, PipelineSpec, RunRecord, RunStatus
from agentflow.store import RunStore


class StaticAdapter(AgentAdapter):
    def prepare(self, node: NodeSpec, prompt: str, paths: ExecutionPaths) -> PreparedExecution:
        return PreparedExecution(
            command=["true"],
            env={},
            cwd=paths.target_workdir,
            trace_kind="raw",
        )


class ExitCodeRunner(Runner):
    def __init__(self, exit_codes: dict[str, int]) -> None:
        self.exit_codes = exit_codes

    def plan_execution(
        self,
        node: NodeSpec,
        prepared: PreparedExecution,
        paths: ExecutionPaths,
    ) -> LaunchPlan:
        return super().plan_execution(node, prepared, paths)

    async def execute(
        self,
        node: NodeSpec,
        prepared: PreparedExecution,
        paths: ExecutionPaths,
        on_output,
        should_cancel,
    ) -> RawExecutionResult:
        exit_code = self.exit_codes.get(node.id, 0)
        if exit_code == 0:
            await on_output("stdout", f"{node.id}: ok")
        else:
            await on_output("stderr", f"{node.id}: failed")
        return RawExecutionResult(exit_code=exit_code)


class SingleAdapterRegistry:
    def __init__(self, adapter: AgentAdapter) -> None:
        self.adapter = adapter

    def get(self, kind: AgentKind) -> AgentAdapter:
        return self.adapter


class SingleRunnerRegistry:
    def __init__(self, runner: Runner) -> None:
        self.runner = runner

    def get(self, kind: str) -> Runner:
        return self.runner


def _run_record(tmp_path: Path, pipeline: PipelineSpec) -> RunRecord:
    return RunRecord(
        id="run",
        status=RunStatus.QUEUED,
        pipeline=pipeline,
        nodes={node.id: NodeResult(node_id=node.id, status=NodeStatus.PENDING) for node in pipeline.nodes},
    )


def test_orchestrator_fail_fast_stage_skips_remaining_nodes(tmp_path: Path) -> None:
    pipeline = PipelineSpec(
        name="fail-fast",
        working_dir=str(tmp_path),
        fail_fast=True,
        concurrency=1,
        nodes=[
            NodeSpec(id="fail", agent=AgentKind.SHELL, prompt="fail"),
            NodeSpec(id="later", agent=AgentKind.SHELL, prompt="later"),
        ],
    )
    store = RunStore(tmp_path / "runs")
    record = _run_record(tmp_path, pipeline)
    record.nodes["fail"].status = NodeStatus.FAILED
    asyncio.run(store.create_run(record))
    orchestrator = Orchestrator(
        store=store,
        adapters=SingleAdapterRegistry(StaticAdapter()),
        runners=SingleRunnerRegistry(ExitCodeRunner({"fail": 1})),
    )
    remaining = {"later"}

    asyncio.run(
        orchestrator._apply_fail_fast(
            run_id="run",
            pipeline=pipeline,
            record=record,
            remaining=remaining,
        )
    )

    assert record.nodes["later"].status == NodeStatus.SKIPPED
    assert "later" not in remaining
    skip_events = [event for event in store.get_events("run") if event.type == "node_skipped"]
    assert any(event.node_id == "later" and event.data.get("reason") == "fail_fast" for event in skip_events)


def test_orchestrator_blocked_stage_skips_nodes_with_upstream_failure(tmp_path: Path) -> None:
    pipeline = PipelineSpec(
        name="upstream-failure",
        working_dir=str(tmp_path),
        concurrency=1,
        nodes=[
            NodeSpec(id="fail", agent=AgentKind.SHELL, prompt="fail"),
            NodeSpec(id="blocked", agent=AgentKind.SHELL, prompt="blocked", depends_on=["fail"]),
        ],
    )
    store = RunStore(tmp_path / "runs")
    record = _run_record(tmp_path, pipeline)
    record.nodes["fail"].status = NodeStatus.FAILED
    asyncio.run(store.create_run(record))
    orchestrator = Orchestrator(
        store=store,
        adapters=SingleAdapterRegistry(StaticAdapter()),
        runners=SingleRunnerRegistry(ExitCodeRunner({"fail": 1})),
    )
    remaining = {"blocked"}
    cycle_state = orchestrator._compute_cycle_state("run", pipeline, pipeline.node_map, record, {})

    asyncio.run(
        orchestrator._skip_blocked_nodes(
            run_id="run",
            node_map=pipeline.node_map,
            record=record,
            remaining=remaining,
            cycle_state=cycle_state,
        )
    )

    assert record.nodes["blocked"].status == NodeStatus.SKIPPED
    assert "blocked" not in remaining
    skip_events = [event for event in store.get_events("run") if event.type == "node_skipped"]
    assert any(event.node_id == "blocked" and event.data.get("reason") == "upstream_failure" for event in skip_events)
