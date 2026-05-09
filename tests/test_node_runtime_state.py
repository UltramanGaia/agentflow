from __future__ import annotations

import asyncio
import json
from pathlib import Path

from agentflow.agents.base import AgentAdapter
from agentflow.orchestrator import Orchestrator
from agentflow.prepared import ExecutionPaths, PreparedExecution
from agentflow.runner import LaunchPlan, RawExecutionResult, Runner
from agentflow.specs import AgentKind, NodeResult, NodeSpec, NodeStatus, PipelineSpec, RunRecord, RunStatus
from agentflow.store import RunStore


class StreamingAdapter(AgentAdapter):
    def prepare(self, node: NodeSpec, prompt: str, paths: ExecutionPaths) -> PreparedExecution:
        return PreparedExecution(
            command=["true"],
            env={},
            cwd=paths.target_workdir,
            trace_kind="raw",
        )


class StreamingRunner(Runner):
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
        await on_output("stdout", "hello from stdout")
        await on_output("stderr", "diagnostic on stderr")
        return RawExecutionResult(exit_code=0)


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


def test_node_result_discards_legacy_runtime_fields() -> None:
    result = NodeResult.model_validate(
        {
            "node_id": "node",
            "status": "completed",
            "stdout_lines": ["legacy stdout"],
            "stderr_lines": ["legacy stderr"],
            "trace_events": [{"kind": "result"}],
            "current_attempt": 3,
            "last_tick_started_at": "2026-05-09T00:00:00+00:00",
            "next_scheduled_at": "2026-05-09T00:01:00+00:00",
        }
    )

    dumped = result.model_dump(mode="json")

    assert dumped["node_id"] == "node"
    assert dumped["status"] == NodeStatus.COMPLETED
    assert "stdout_lines" not in dumped
    assert "stderr_lines" not in dumped
    assert "trace_events" not in dumped
    assert "current_attempt" not in dumped
    assert "last_tick_started_at" not in dumped
    assert "next_scheduled_at" not in dumped


def test_orchestrator_persists_result_without_runtime_state(tmp_path: Path) -> None:
    node = NodeSpec(id="node", agent=AgentKind.SHELL, prompt="run")
    pipeline = PipelineSpec(name="runtime-state-test", working_dir=str(tmp_path), nodes=[node])
    run = RunRecord(
        id="run",
        status=RunStatus.RUNNING,
        pipeline=pipeline,
        nodes={"node": NodeResult(node_id="node", status=NodeStatus.PENDING)},
    )
    store = RunStore(tmp_path / "runs")
    asyncio.run(store.create_run(run))
    orchestrator = Orchestrator(
        store=store,
        adapters=SingleAdapterRegistry(StreamingAdapter()),
        runners=SingleRunnerRegistry(StreamingRunner()),
    )

    asyncio.run(orchestrator._execute_node("run", "node"))

    run_payload = json.loads((tmp_path / "runs" / "run" / "run.json").read_text(encoding="utf-8"))
    result_payload = json.loads(
        (tmp_path / "runs" / "run" / "artifacts" / "node" / "result.json").read_text(encoding="utf-8")
    )
    stdout_log = (tmp_path / "runs" / "run" / "artifacts" / "node" / "stdout.log").read_text(encoding="utf-8")
    stderr_log = (tmp_path / "runs" / "run" / "artifacts" / "node" / "stderr.log").read_text(encoding="utf-8")

    for payload in (run_payload["nodes"]["node"], result_payload):
        assert payload["output"] == "hello from stdout"
        assert "stdout_lines" not in payload
        assert "stderr_lines" not in payload
        assert "trace_events" not in payload
        assert "current_attempt" not in payload

    assert "hello from stdout" in stdout_log
    assert "diagnostic on stderr" in stderr_log
