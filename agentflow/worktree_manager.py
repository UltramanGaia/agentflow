from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from agentflow import worktree
from agentflow.specs import NodeSpec, PipelineSpec


@dataclass(slots=True)
class WorktreeLease:
    repo_dir: Path
    worktree_dir: Path


@dataclass(slots=True)
class PreparedWorktreeNode:
    node: NodeSpec
    lease: WorktreeLease | None = None
    warning: str | None = None


class WorktreeManager:
    def prepare_node(self, pipeline: PipelineSpec, node: NodeSpec, *, run_id: str) -> PreparedWorktreeNode:
        if not pipeline.use_worktree:
            return PreparedWorktreeNode(node=node)
        if not worktree.is_git_repo(pipeline.working_path):
            return PreparedWorktreeNode(node=node)
        try:
            worktree_dir = worktree.create_worktree(pipeline.working_path, node.id, run_id)
        except Exception as exc:
            return PreparedWorktreeNode(node=node, warning=f"Worktree failed: {exc}")

        target = node.target.model_copy(update={"cwd": str(worktree_dir)})
        return PreparedWorktreeNode(
            node=node.model_copy(update={"target": target}),
            lease=WorktreeLease(repo_dir=pipeline.working_path, worktree_dir=worktree_dir),
        )

    def capture_diff_and_cleanup(self, lease: WorktreeLease | None) -> str:
        if lease is None:
            return ""

        diff = ""
        try:
            diff = worktree.get_worktree_diff(lease.worktree_dir)
        except Exception:
            diff = ""
        finally:
            try:
                worktree.remove_worktree(lease.repo_dir, lease.worktree_dir)
            except Exception:
                pass
        return diff
