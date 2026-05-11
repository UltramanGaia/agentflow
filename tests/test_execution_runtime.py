from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import cast

import pytest

from agentflow.agents.base import AgentAdapter
from agentflow.node_executor import NodeExecutor
from agentflow.prepared import ExecutionPaths, PreparedExecution
from agentflow.run_state import RunStateRegistry
from agentflow.runner import LaunchPlan, LocalRunner, RawExecutionResult
from agentflow.scratchboard_manager import ScratchboardManager
from agentflow.specs import AgentKind, NodeResult, NodeSpec, PipelineSpec, RunRecord
from agentflow.store import RunStore
from agentflow.worktree_manager import WorktreeManager


class FastFailLocalRunner(LocalRunner):
    async def _wait_for_exit(self, wait_task: asyncio.Task[int], timeout: float) -> bool:
        if timeout == 5 and not wait_task.done():
            return False
        return await super()._wait_for_exit(wait_task, timeout)


class StubAdapter(AgentAdapter):
    def prepare(self, node: NodeSpec, prompt: str, paths: ExecutionPaths) -> PreparedExecution:
        return PreparedExecution(
            command=["stub-agent"],
            env={},
            cwd=paths.target_workdir,
            trace_kind="shell",
        )


class InspectingRunner:
    def __init__(self, runs_dir: Path, run_id: str) -> None:
        self.runs_dir = runs_dir
        self.run_id = run_id

    def plan_execution(self, node: NodeSpec, prepared: PreparedExecution, paths: ExecutionPaths) -> LaunchPlan:
        return LaunchPlan(command=list(prepared.command), cwd=prepared.cwd, env=dict(prepared.env))

    async def execute(
        self,
        node: NodeSpec,
        prepared: PreparedExecution,
        paths: ExecutionPaths,
        on_output,
        should_cancel,
    ) -> RawExecutionResult:
        run_path = self.runs_dir / self.run_id / "run.json"
        payload = json.loads(run_path.read_text(encoding="utf-8"))
        node_state = payload["nodes"][node.id]
        assert node_state["status"] == "running"
        assert node_state["started_at"] is not None
        await on_output("stdout", "ok")
        return RawExecutionResult(exit_code=0, stdout_lines=["ok"])


async def _noop_output(stream_name: str, line: str) -> None:
    return None


class FakeStream:
    async def readline(self) -> bytes:
        return b""


class FakeProcess:
    def __init__(self) -> None:
        self.stdout = FakeStream()
        self.stderr = FakeStream()
        self.stdin = None
        self.returncode: int | None = None
        self._wait_event = asyncio.Event()

    async def wait(self) -> int:
        await self._wait_event.wait()
        return self.returncode if self.returncode is not None else 0

    def terminate(self) -> None:
        self.returncode = 0
        self._wait_event.set()

    def kill(self) -> None:
        self.returncode = -9
        self._wait_event.set()


def test_local_runner_marks_execution_error_as_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    runner = FastFailLocalRunner()
    node = NodeSpec(id="merge", agent=AgentKind.SHELL, prompt="noop")
    prepared = PreparedExecution(
        command=["fake-agent"],
        env={},
        cwd=str(tmp_path),
        trace_kind="shell",
    )
    paths = ExecutionPaths(
        host_workdir=tmp_path,
        host_runtime_dir=runtime_dir,
        target_workdir=str(tmp_path),
        target_runtime_dir=str(runtime_dir),
        app_root=tmp_path,
    )

    async def fake_create_subprocess_exec(*args, **kwargs) -> FakeProcess:
        return FakeProcess()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    raw = asyncio.run(runner.execute(node, prepared, paths, _noop_output, lambda: False))

    assert raw.exit_code != 0
    assert any("process did not exit after stdout/stderr closed" in line for line in raw.stderr_lines)


def test_node_executor_persists_running_state_before_runner_executes(tmp_path: Path) -> None:
    pipeline = PipelineSpec(
        name="persist-running",
        working_dir=str(tmp_path),
        nodes=[NodeSpec(id="plan", agent=AgentKind.SHELL, prompt="noop")],
    )
    run_id = "run-persist-running"
    record = RunRecord(
        id=run_id,
        pipeline=pipeline,
        nodes={"plan": NodeResult(node_id="plan")},
    )
    store = RunStore(tmp_path / "runs")
    asyncio.run(store.create_run(record))

    adapters = {
        AgentKind.SHELL: cast(AgentAdapter, StubAdapter()),
    }
    run_state = RunStateRegistry()
    run_state.ensure_run(run_id)
    runner = InspectingRunner(store.base_dir, run_id)

    async def publish(run_id: str, event_type: str, **data) -> None:
        return None

    executor = NodeExecutor(
        store=store,
        adapters=adapters,
        runner=runner,
        worktrees=WorktreeManager(),
        scratchboards=ScratchboardManager(),
        publish=publish,
        node_runtime_state=run_state.runtime_state,
        runtime_states_for_run=run_state.runtime_states_for_run,
        should_cancel=lambda _: False,
        should_cancel_node=lambda *_: False,
    )

    asyncio.run(executor.execute(run_id, "plan"))

    persisted = json.loads((store.run_dir(run_id) / "run.json").read_text(encoding="utf-8"))
    assert persisted["nodes"]["plan"]["status"] == "completed"
    assert persisted["nodes"]["plan"]["output"] == "ok"
