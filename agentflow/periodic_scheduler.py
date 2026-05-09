from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from agentflow.run_state import RunStateRegistry
from agentflow.periodic import PeriodicActionEnvelope
from agentflow.specs import NodeResult, NodeStatus, PipelineSpec
from agentflow.store import RunStore
from agentflow.utils import utcnow_iso


_TERMINAL_NODE_STATUSES = {
    NodeStatus.COMPLETED,
    NodeStatus.FAILED,
    NodeStatus.SKIPPED,
    NodeStatus.CANCELLED,
}


PublishEvent = Callable[..., Awaitable[None]]


@dataclass(slots=True)
class PeriodicScheduler:
    store: RunStore
    publish: PublishEvent
    run_state: RunStateRegistry

    def fanout_group_settled(self, pipeline: PipelineSpec, results: dict[str, NodeResult], group_id: str) -> bool:
        member_ids = pipeline.fanouts.get(group_id, [])
        if not member_ids:
            return True
        return all(results[member_id].status in _TERMINAL_NODE_STATUSES for member_id in member_ids)

    async def finalize_node(self, run_id: str, node_id: str, *, reason: str) -> None:
        record = self.store.get_run(run_id)
        result = record.nodes[node_id]
        if result.status == NodeStatus.COMPLETED:
            return
        result.status = NodeStatus.COMPLETED
        result.success = True if result.success is None else result.success
        self.run_state.runtime_state(run_id, node_id).next_scheduled_at = None
        result.finished_at = result.finished_at or utcnow_iso()
        await self.publish(
            run_id,
            "node_completed",
            node_id=node_id,
            tick_count=result.tick_count,
            reason=reason,
            output=result.output,
            final_response=result.final_response,
            success=result.success,
            success_details=result.success_details,
        )
        await self.store.write_artifact_text(run_id, node_id, "output.txt", result.output or "")
        await self.store.write_artifact_json(run_id, node_id, "result.json", result.model_dump(mode="json"))
        await self.store.persist_run(run_id)

    async def apply_actions(
        self,
        run_id: str,
        controller_node_id: str,
        *,
        watched_group: str,
        actions: PeriodicActionEnvelope,
        remaining: set[str],
        in_progress: dict[str, Any],
    ) -> None:
        """Apply controller actions emitted by a periodic node to its watched fanout."""

        if not actions.actions:
            return

        record = self.store.get_run(run_id)
        allowed_node_ids = set(record.pipeline.fanouts.get(watched_group, []))

        ordered_actions = sorted(actions.actions, key=lambda item: 0 if item.kind == "cancel" else 1)
        applied: list[dict[str, Any]] = []
        rejected: list[dict[str, Any]] = []

        for action in ordered_actions:
            kind = action.kind.strip().lower()
            if kind not in {"cancel", "rerun"}:
                rejected.append({"kind": action.kind, "node_ids": list(action.node_ids), "reason": "unsupported_action"})
                continue
            for target_node_id in action.node_ids:
                if target_node_id not in allowed_node_ids:
                    rejected.append({"kind": kind, "node_id": target_node_id, "reason": "outside_watched_fanout"})
                    continue
                target_result = record.nodes[target_node_id]
                if kind == "cancel":
                    if target_result.status not in {NodeStatus.QUEUED, NodeStatus.RUNNING, NodeStatus.RETRYING}:
                        rejected.append({"kind": kind, "node_id": target_node_id, "reason": "node_not_running"})
                        continue
                    self.run_state.request_node_cancel(run_id, target_node_id)
                    applied.append({"kind": kind, "node_id": target_node_id, "reason": action.reason})
                    continue

                if target_result.status in {NodeStatus.PENDING, NodeStatus.READY}:
                    rejected.append({"kind": kind, "node_id": target_node_id, "reason": "node_not_started"})
                    continue
                self.run_state.queue_node_rerun(run_id, target_node_id)
                if target_result.status in _TERMINAL_NODE_STATUSES and target_node_id not in in_progress:
                    target_result.status = NodeStatus.PENDING
                    self.run_state.runtime_state(run_id, target_node_id).next_scheduled_at = None
                    remaining.add(target_node_id)
                applied.append({"kind": kind, "node_id": target_node_id, "reason": action.reason})

        if applied:
            await self.publish(
                run_id,
                "node_control_actions_applied",
                node_id=controller_node_id,
                watched_group=watched_group,
                actions=applied,
            )
        if rejected:
            await self.publish(
                run_id,
                "node_control_actions_rejected",
                node_id=controller_node_id,
                watched_group=watched_group,
                actions=rejected,
            )
