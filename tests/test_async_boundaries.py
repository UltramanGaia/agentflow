from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Callable

import agentflow.graph_optimization_session as graph_optimization_session_module
import agentflow.store as store_module
from agentflow.graph_optimization_session import run_optimizer_in_thread
from agentflow.specs import AgentKind, NodeResult, NodeSpec, NodeStatus, PipelineSpec, RunEvent, RunRecord, RunStatus
from agentflow.store import RunStore


def _run_record(run_id: str, tmp_path: Path) -> RunRecord:
    pipeline = PipelineSpec(
        name="async-boundaries",
        working_dir=str(tmp_path),
        nodes=[NodeSpec(id="node", agent=AgentKind.SHELL, prompt="run")],
    )
    return RunRecord(
        id=run_id,
        status=RunStatus.QUEUED,
        pipeline=pipeline,
        nodes={"node": NodeResult(node_id="node", status=NodeStatus.PENDING)},
    )


def test_run_store_async_writes_use_thread_boundary(
    tmp_path: Path,
    monkeypatch,
) -> None:
    calls: list[str] = []
    original_to_thread = asyncio.to_thread

    async def capturing_to_thread(func: Callable[..., Any], /, *args: Any, **kwargs: Any) -> Any:
        calls.append(func.__name__)
        return await original_to_thread(func, *args, **kwargs)

    monkeypatch.setattr(store_module.asyncio, "to_thread", capturing_to_thread)
    store = RunStore(tmp_path / "runs")
    store._runs["run"] = _run_record("run", tmp_path)

    async def run_store_operations() -> None:
        await store.persist_run("run")
        await store.append_event("run", RunEvent(run_id="run", type="custom"))
        await store.request_cancel("run")
        await store.clear_cancel_request("run")
        await store.append_artifact_text("run", "node", "stdout.log", "hello\n")
        await store.write_artifact_text("run", "node", "output.txt", "done")

    asyncio.run(run_store_operations())

    assert calls == [
        "_persist_run_sync",
        "_append_event_sync",
        "_request_cancel_sync",
        "_clear_cancel_request_sync",
        "_append_artifact_text_sync",
        "_write_artifact_text_sync",
    ]


def test_graph_optimizer_runs_through_thread_boundary(tmp_path: Path, monkeypatch) -> None:
    calls: list[str] = []

    def fake_run_optimizer(*args: Any, **kwargs: Any) -> str:
        return "optimizer-result"

    async def capturing_to_thread(func: Callable[..., Any], /, *args: Any, **kwargs: Any) -> Any:
        calls.append(func.__name__)
        return func(*args, **kwargs)

    monkeypatch.setattr(graph_optimization_session_module, "_run_optimizer", fake_run_optimizer)
    monkeypatch.setattr(graph_optimization_session_module.asyncio, "to_thread", capturing_to_thread)

    result = asyncio.run(
        run_optimizer_in_thread(
            AgentKind.CODEX,
            prompt="optimize",
            repo_dir=tmp_path,
            runtime_dir=tmp_path / "runtime",
            env={},
        )
    )

    assert result == "optimizer-result"
    assert calls == ["fake_run_optimizer"]
