from __future__ import annotations

from pathlib import Path

import pytest

from agentflow import worktree
from agentflow.specs import AgentKind, LocalTarget, NodeSpec, PipelineSpec
from agentflow.worktree_manager import WorktreeLease, WorktreeManager


def test_worktree_manager_prepares_local_node_in_worktree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    worktree_dir = tmp_path / "worktree"

    monkeypatch.setattr(worktree, "is_git_repo", lambda path: True)
    monkeypatch.setattr(worktree, "create_worktree", lambda repo, node_id, run_id: worktree_dir)

    node = NodeSpec(id="node", agent=AgentKind.SHELL, prompt="run")
    pipeline = PipelineSpec(name="worktree", working_dir=str(repo_dir), use_worktree=True, nodes=[node])

    prepared = WorktreeManager().prepare_node(pipeline, node, run_id="run")

    assert prepared.warning is None
    assert prepared.lease == WorktreeLease(repo_dir=pipeline.working_path, worktree_dir=worktree_dir)
    assert isinstance(prepared.node.target, LocalTarget)
    assert prepared.node.target.cwd == str(worktree_dir)
    assert node.target.cwd is None


def test_worktree_manager_returns_warning_on_create_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()

    def fail_create(repo, node_id, run_id):
        raise RuntimeError("boom")

    monkeypatch.setattr(worktree, "is_git_repo", lambda path: True)
    monkeypatch.setattr(worktree, "create_worktree", fail_create)

    node = NodeSpec(id="node", agent=AgentKind.SHELL, prompt="run")
    pipeline = PipelineSpec(name="worktree", working_dir=str(repo_dir), use_worktree=True, nodes=[node])

    prepared = WorktreeManager().prepare_node(pipeline, node, run_id="run")

    assert prepared.node == node
    assert prepared.lease is None
    assert prepared.warning == "Worktree failed: boom"


def test_worktree_manager_captures_diff_and_cleans_up(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, Path]] = []
    repo_dir = tmp_path / "repo"
    worktree_dir = tmp_path / "worktree"

    def get_diff(path: Path) -> str:
        calls.append(("diff", path))
        return "diff --git a/file b/file\n"

    def remove(repo: Path, path: Path) -> None:
        calls.append(("remove", path))

    monkeypatch.setattr(worktree, "get_worktree_diff", get_diff)
    monkeypatch.setattr(worktree, "remove_worktree", remove)

    diff = WorktreeManager().capture_diff_and_cleanup(WorktreeLease(repo_dir=repo_dir, worktree_dir=worktree_dir))

    assert diff == "diff --git a/file b/file\n"
    assert calls == [("diff", worktree_dir), ("remove", worktree_dir)]
