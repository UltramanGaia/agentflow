from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from agentflow.agents.base import AgentAdapter
from agentflow.orchestrator import Orchestrator
from agentflow.prepared import ExecutionPaths, PreparedExecution
from agentflow.runner import LaunchPlan, RawExecutionResult, default_launch_plan
from agentflow.specs import (
    AgentKind,
    LocalTarget,
    NodeResult,
    NodeSpec,
    NodeStatus,
    PipelineSpec,
    RunRecord,
    RunStatus,
)
from agentflow.store import RunStore


class CapturingAdapter(AgentAdapter):
    def __init__(self) -> None:
        self.node: NodeSpec | None = None
        self.paths: ExecutionPaths | None = None

    def prepare(self, node: NodeSpec, prompt: str, paths: ExecutionPaths) -> PreparedExecution:
        self.node = node
        self.paths = paths
        return PreparedExecution(
            command=["true"],
            env={},
            cwd=paths.target_workdir,
            trace_kind="raw",
        )


class CapturingRunner:
    def __init__(self) -> None:
        self.node: NodeSpec | None = None
        self.paths: ExecutionPaths | None = None

    def plan_execution(
        self,
        node: NodeSpec,
        prepared: PreparedExecution,
        paths: ExecutionPaths,
    ) -> LaunchPlan:
        self.node = node
        self.paths = paths
        return default_launch_plan(prepared)

    async def execute(
        self,
        node: NodeSpec,
        prepared: PreparedExecution,
        paths: ExecutionPaths,
        on_output,
        should_cancel,
    ) -> RawExecutionResult:
        self.node = node
        self.paths = paths
        return RawExecutionResult(exit_code=0)


class SingleAdapterRegistry:
    def __init__(self, adapter: AgentAdapter) -> None:
        self.adapter = adapter

    def get(self, kind: AgentKind) -> AgentAdapter:
        return self.adapter


def test_worktree_execution_preserves_node_and_target_models(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import agentflow.worktree as worktree

    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    worktree_dir = tmp_path / "worktree"
    worktree_dir.mkdir()

    monkeypatch.setattr(worktree, "is_git_repo", lambda path: True)
    monkeypatch.setattr(worktree, "create_worktree", lambda repo, node_id, run_id: worktree_dir)
    monkeypatch.setattr(worktree, "get_worktree_diff", lambda path: "")
    monkeypatch.setattr(worktree, "remove_worktree", lambda repo, path: None)

    node = NodeSpec(id="node", agent=AgentKind.SHELL, prompt="run")
    pipeline = PipelineSpec(name="worktree-test", working_dir=str(repo_dir), use_worktree=True, nodes=[node])
    run = RunRecord(
        id="run",
        status=RunStatus.RUNNING,
        pipeline=pipeline,
        nodes={"node": NodeResult(node_id="node", status=NodeStatus.PENDING)},
    )

    store = RunStore(tmp_path / "runs")
    asyncio.run(store.create_run(run))

    adapter = CapturingAdapter()
    runner = CapturingRunner()
    orchestrator = Orchestrator(
        store=store,
        adapters=SingleAdapterRegistry(adapter),
        runner=runner,
    )

    asyncio.run(orchestrator._execute_node("run", "node"))

    assert isinstance(adapter.node, NodeSpec)
    assert isinstance(adapter.node.target, LocalTarget)
    assert adapter.node.target.cwd == str(worktree_dir)
    assert adapter.paths is not None
    assert adapter.paths.host_workdir == worktree_dir.resolve()
    assert pipeline.nodes[0].target.cwd is None

    assert isinstance(runner.node, NodeSpec)
    assert isinstance(runner.node.target, LocalTarget)
    assert store.get_run("run").nodes["node"].status == NodeStatus.COMPLETED
