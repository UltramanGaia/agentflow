from __future__ import annotations

import shutil
from pathlib import Path

from agentflow.scratchboard import SCRATCHBOARD_FILENAME
from agentflow.specs_core import NodeStatus, RunStatus
from agentflow.specs_models import NodeResult, RunRecord
from agentflow.store import RunStore
from agentflow.utils import utcnow_iso


def build_resumed_run(old_record: RunRecord, *, new_run_id: str) -> RunRecord:
    nodes: dict[str, NodeResult] = {}
    for node in old_record.pipeline.nodes:
        old_node = old_record.nodes.get(node.id)
        if old_node is not None and old_node.status == NodeStatus.COMPLETED:
            nodes[node.id] = old_node.model_copy()
        else:
            nodes[node.id] = NodeResult(node_id=node.id, status=NodeStatus.PENDING)

    return RunRecord(
        id=new_run_id,
        status=RunStatus.QUEUED,
        pipeline=old_record.pipeline,
        nodes=nodes,
    )


def copy_resume_artifacts(store: RunStore, *, source_run_id: str, resumed_run: RunRecord) -> None:
    old_run_dir = store.run_dir(source_run_id)
    new_run_dir = store.run_dir(resumed_run.id)
    old_sb = old_run_dir / SCRATCHBOARD_FILENAME
    if old_sb.exists():
        shutil.copy2(str(old_sb), str(new_run_dir / SCRATCHBOARD_FILENAME))

    old_artifacts = old_run_dir / "artifacts"
    new_artifacts = new_run_dir / "artifacts"
    for node_id, node_result in resumed_run.nodes.items():
        if node_result.status != NodeStatus.COMPLETED:
            continue
        src = old_artifacts / node_id
        if src.is_dir():
            dst = new_artifacts / node_id
            dst.mkdir(parents=True, exist_ok=True)
            shutil.copytree(str(src), str(dst), dirs_exist_ok=True)


def finalize_cancelled_queued_run(record: RunRecord) -> RunRecord:
    record.status = RunStatus.CANCELLED
    record.finished_at = utcnow_iso()
    for node in record.nodes.values():
        if node.status in {NodeStatus.PENDING, NodeStatus.QUEUED, NodeStatus.READY}:
            node.status = NodeStatus.CANCELLED
            node.finished_at = record.finished_at
    return record


def build_rerun_node_run(
    old_record: RunRecord,
    *,
    new_run_id: str,
    rerun_nodes: set[str],
) -> RunRecord:
    nodes: dict[str, NodeResult] = {}
    for node in old_record.pipeline.nodes:
        old_node = old_record.nodes.get(node.id)
        if node.id not in rerun_nodes and old_node is not None and old_node.status == NodeStatus.COMPLETED:
            nodes[node.id] = old_node.model_copy()
        else:
            nodes[node.id] = NodeResult(node_id=node.id, status=NodeStatus.PENDING)

    return RunRecord(
        id=new_run_id,
        status=RunStatus.QUEUED,
        pipeline=old_record.pipeline,
        nodes=nodes,
    )
