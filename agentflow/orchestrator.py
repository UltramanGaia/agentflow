"""Async pipeline orchestration for AgentFlow runs.

Each submitted run is driven in a background thread that owns one asyncio loop.
Threads provide run-level isolation and concurrency limits; asyncio handles
per-run node scheduling and streaming. Blocking subprocess or filesystem work
on async paths should cross the boundary explicitly with ``asyncio.to_thread``.
"""

from __future__ import annotations

import asyncio
from copy import deepcopy
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from agentflow.agents.registry import AdapterRegistry, default_adapter_registry
from agentflow.graph_optimization_session import GraphOptimizationSession
from agentflow.node_executor import NodeExecutionOutcome, NodeExecutor
from agentflow.periodic_scheduler import PeriodicScheduler
from agentflow.run_lifecycle import (
    build_rerun_node_run,
    build_resumed_run,
    copy_resume_artifacts,
    finalize_cancelled_queued_run,
)
from agentflow.run_state import PeriodicNodeRuntimeState, RunStateRegistry
from agentflow.runner import LocalRunner, Runner
from agentflow.scratchboard_manager import ScratchboardManager
from agentflow.specs import (
    NodeResult,
    NodeStatus,
    PipelineSpec,
    RunEvent,
    RunRecord,
    RunStatus,
)
from agentflow.store import RunStore
from agentflow.utils import utcnow_iso
from agentflow.worktree_manager import WorktreeManager


_TERMINAL_NODE_STATUSES = {
    NodeStatus.COMPLETED,
    NodeStatus.FAILED,
    NodeStatus.SKIPPED,
    NodeStatus.CANCELLED,
}


@dataclass(slots=True)
class _CycleState:
    cycle_nodes: set[str]
    cycle_tail_nodes: set[str]
    active_cycle_tails: set[str]
    cycle_downstream: set[str]

@dataclass(slots=True)
class Orchestrator:
    """Coordinate pipeline run lifecycles against the persistent run store.

    The orchestrator accepts submissions, starts bounded background workers, and
    advances each run by scheduling ready nodes until the run completes, fails, or
    is cancelled.
    """

    store: RunStore
    adapters: AdapterRegistry = default_adapter_registry
    runner: Runner = field(default_factory=LocalRunner)
    worktrees: WorktreeManager = field(default_factory=WorktreeManager)
    scratchboards: ScratchboardManager = field(default_factory=ScratchboardManager)
    max_concurrent_runs: int = 2
    _run_slots: threading.Semaphore = field(init=False, repr=False)
    _run_state: RunStateRegistry = field(default_factory=RunStateRegistry, init=False, repr=False)

    def __post_init__(self) -> None:
        self._run_slots = threading.Semaphore(self.max_concurrent_runs)

    def _clear_run_control_state(self, run_id: str) -> None:
        self._run_state.clear_run(run_id)
        self.scratchboards.clear_run(run_id)

    def _periodic_scheduler(self) -> PeriodicScheduler:
        return PeriodicScheduler(
            store=self.store,
            publish=self._publish,
            run_state=self._run_state,
        )

    def _node_executor(self) -> NodeExecutor:
        return NodeExecutor(
            store=self.store,
            adapters=self.adapters,
            runner=self.runner,
            worktrees=self.worktrees,
            scratchboards=self.scratchboards,
            publish=self._publish,
            node_runtime_state=self._run_state.runtime_state,
            runtime_states_for_run=self._run_state.runtime_states_for_run,
            should_cancel=self._should_cancel,
            should_cancel_node=self._should_cancel_node,
        )

    @staticmethod
    def _reset_node_for_cycle(record: "RunRecord", node_id: str, remaining: set[str]) -> None:
        """Reset a node to PENDING so it can be re-executed in a cycle."""
        node_result = record.nodes.get(node_id)
        if node_result is None:
            return
        node_result.status = NodeStatus.PENDING
        node_result.finished_at = None
        node_result.output = None
        node_result.exit_code = None
        node_result.success = None
        node_result.success_details = []
        remaining.add(node_id)

    @staticmethod
    def _nodes_between(node_map: dict[str, "NodeSpec"], start_id: str, end_id: str) -> list[str]:
        """Find node IDs on the path from start to end (exclusive of both endpoints)."""
        # BFS forward from start following depends_on edges in reverse
        reverse_deps: dict[str, list[str]] = {}
        for nid, node in node_map.items():
            for dep in node.depends_on:
                reverse_deps.setdefault(dep, []).append(nid)

        visited: set[str] = set()
        queue = [start_id]
        while queue:
            current = queue.pop(0)
            for downstream in reverse_deps.get(current, []):
                if downstream == end_id:
                    continue
                if downstream not in visited:
                    visited.add(downstream)
                    queue.append(downstream)
        return [nid for nid in visited if nid != start_id]

    @staticmethod
    def _node_output_text(node_result: NodeResult | None) -> str:
        if node_result is None:
            return ""
        return str(node_result.output or node_result.final_response or "")

    @classmethod
    def _should_skip_node(cls, node: "NodeSpec", record: RunRecord) -> tuple[bool, str | None]:
        for criterion in node.skip_if:
            if criterion.kind == "node_output_contains":
                source = record.nodes.get(criterion.node_id)
                haystack = cls._node_output_text(source)
                needle = str(criterion.value)
                if not criterion.case_sensitive:
                    haystack = haystack.lower()
                    needle = needle.lower()
                if needle and needle in haystack:
                    return True, f"{criterion.kind}:{criterion.node_id}:{criterion.value}"
        return False, None

    def _initialize_run_tracking(self, run_id: str, *, cancel_flag: threading.Event | None = None) -> None:
        self._run_state.ensure_run(run_id, cancel_flag=cancel_flag)

    def _compute_cycle_state(
        self,
        run_id: str,
        pipeline: PipelineSpec,
        node_map: dict[str, "NodeSpec"],
        record: RunRecord,
        iteration_counts: dict[tuple[str, str], int],
    ) -> _CycleState:
        cycle_nodes: set[str] = set()
        cycle_tail_nodes: set[str] = set()
        for node in pipeline.nodes:
            if not node.on_failure_restart:
                continue
            cycle_tail_nodes.add(node.id)
            cycle_nodes.add(node.id)
            cycle_nodes.update(node.on_failure_restart)
            for target_id in node.on_failure_restart:
                cycle_nodes.update(self._nodes_between(node_map, target_id, node.id))

        active_cycle_tails: set[str] = set()
        for tail_id in cycle_tail_nodes:
            iter_key = (run_id, tail_id)
            tail_status = record.nodes[tail_id].status
            if tail_status != NodeStatus.COMPLETED and iteration_counts.get(iter_key, 0) < pipeline.max_iterations:
                active_cycle_tails.add(tail_id)

        cycle_downstream: set[str] = set()
        for node in pipeline.nodes:
            if any(dep in active_cycle_tails for dep in node.depends_on):
                cycle_downstream.add(node.id)

        return _CycleState(
            cycle_nodes=cycle_nodes,
            cycle_tail_nodes=cycle_tail_nodes,
            active_cycle_tails=active_cycle_tails,
            cycle_downstream=cycle_downstream,
        )

    def _blocked_nodes(
        self,
        remaining: set[str],
        *,
        node_map: dict[str, "NodeSpec"],
        record: RunRecord,
        cycle_state: _CycleState,
    ) -> list[str]:
        return [
            node_id
            for node_id in list(remaining)
            if (
                any(
                    record.nodes[dependency].status in {NodeStatus.SKIPPED, NodeStatus.CANCELLED}
                    for dependency in node_map[node_id].depends_on
                )
                or (
                    node_id not in cycle_state.cycle_nodes
                    and node_id not in cycle_state.cycle_downstream
                    and any(record.nodes[dependency].status == NodeStatus.FAILED for dependency in node_map[node_id].depends_on)
                )
            )
        ]

    def _ready_node_ids(
        self,
        remaining: set[str],
        *,
        in_progress: dict[str, asyncio.Task[NodeExecutionOutcome]],
        now: float,
        node_map: dict[str, "NodeSpec"],
        record: RunRecord,
        cycle_state: _CycleState,
        periodic_state: dict[str, PeriodicNodeRuntimeState],
    ) -> list[str]:
        ready: list[str] = []
        for node_id in list(remaining):
            if node_id in in_progress:
                continue
            node = node_map[node_id]
            if node_id in cycle_state.cycle_nodes or node.on_failure_restart:
                terminal = {NodeStatus.COMPLETED, NodeStatus.FAILED}
                if not all(record.nodes[dep].status in terminal for dep in node.depends_on):
                    continue
            elif not all(record.nodes[dep].status == NodeStatus.COMPLETED for dep in node.depends_on):
                continue

            if node.schedule is None:
                ready.append(node_id)
                continue
            state = periodic_state[node_id]
            if state.next_tick_at is None or now >= state.next_tick_at:
                ready.append(node_id)
        return ready

    async def _handle_periodic_completion(
        self,
        *,
        run_id: str,
        node_id: str,
        node: "NodeSpec",
        outcome: NodeExecutionOutcome,
        pipeline: PipelineSpec,
        record: RunRecord,
        periodic_scheduler: PeriodicScheduler,
        periodic_state: dict[str, PeriodicNodeRuntimeState],
        remaining: set[str],
        in_progress: dict[str, asyncio.Task[NodeExecutionOutcome]],
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        if outcome.periodic_actions is not None:
            await self.store.write_artifact_json(
                run_id,
                node_id,
                f"periodic-actions-tick-{outcome.periodic_tick_number}.json",
                outcome.periodic_actions.model_dump(mode="json"),
            )
        elif outcome.periodic_action_parse_error is not None:
            await self.store.write_artifact_json(
                run_id,
                node_id,
                f"periodic-actions-tick-{outcome.periodic_tick_number}.json",
                {"error": outcome.periodic_action_parse_error},
            )
            await self._publish(
                run_id,
                "node_control_actions_rejected",
                node_id=node_id,
                watched_group=node.schedule.until_fanout_settles_from,
                actions=[{"reason": outcome.periodic_action_parse_error}],
            )

        if outcome.periodic_actions is not None:
            await periodic_scheduler.apply_actions(
                run_id,
                node_id,
                watched_group=node.schedule.until_fanout_settles_from,
                actions=outcome.periodic_actions,
                remaining=remaining,
                in_progress=in_progress,
            )

        node_result = record.nodes[node_id]
        if node_result.status != NodeStatus.READY or self._should_cancel(run_id):
            return
        if periodic_scheduler.fanout_group_settled(
            pipeline,
            record.nodes,
            node.schedule.until_fanout_settles_from,
        ):
            await periodic_scheduler.finalize_node(run_id, node_id, reason="watched_group_settled")
            return

        state = periodic_state[node_id]
        if state.last_tick_started_mono is None:
            state.next_tick_at = loop.time() + node.schedule.every_seconds
        else:
            state.next_tick_at = state.last_tick_started_mono + node.schedule.every_seconds
        seconds_until_next_tick = max(state.next_tick_at - loop.time(), 0.0)
        next_tick_at = datetime.now(timezone.utc) + timedelta(seconds=seconds_until_next_tick)
        runtime_state = self._run_state.runtime_state(run_id, node_id)
        runtime_state.next_scheduled_at = next_tick_at.isoformat()
        remaining.add(node_id)
        await self._publish(
            run_id,
            "node_waiting",
            node_id=node_id,
            tick_count=node_result.tick_count,
            next_scheduled_at=runtime_state.next_scheduled_at,
        )
        await self.store.persist_run(run_id)

    async def _handle_cycle_restart(
        self,
        *,
        run_id: str,
        node_id: str,
        node: "NodeSpec",
        pipeline: PipelineSpec,
        node_map: dict[str, "NodeSpec"],
        record: RunRecord,
        iteration_counts: dict[tuple[str, str], int],
        remaining: set[str],
    ) -> None:
        if (
            record.nodes[node_id].status != NodeStatus.FAILED
            or not node.on_failure_restart
            or self._should_cancel(run_id)
        ):
            return

        iteration_key = (run_id, node_id)
        iteration_counts[iteration_key] = iteration_counts.get(iteration_key, 0) + 1
        if iteration_counts[iteration_key] < pipeline.max_iterations:
            await self._publish(
                run_id, "node_cycle_restart",
                node_id=node_id,
                iteration=iteration_counts[iteration_key],
                restart_targets=node.on_failure_restart,
            )
            record.nodes[node_id].status = NodeStatus.PENDING
            record.nodes[node_id].finished_at = None
            remaining.add(node_id)
            for target_id in node.on_failure_restart:
                self._reset_node_for_cycle(record, target_id, remaining)
                for mid_id in self._nodes_between(node_map, target_id, node_id):
                    self._reset_node_for_cycle(record, mid_id, remaining)
            for dep_node in pipeline.nodes:
                if (
                    node_id in dep_node.depends_on
                    and record.nodes.get(dep_node.id)
                    and record.nodes[dep_node.id].status == NodeStatus.SKIPPED
                ):
                    self._reset_node_for_cycle(record, dep_node.id, remaining)
            await self.store.persist_run(run_id)
            return

        await self._publish(
            run_id, "node_cycle_exhausted",
            node_id=node_id,
            max_iterations=pipeline.max_iterations,
        )

    async def _handle_terminal_rerun(
        self,
        *,
        run_id: str,
        node_id: str,
        record: RunRecord,
        remaining: set[str],
    ) -> None:
        if (
            record.nodes[node_id].status not in _TERMINAL_NODE_STATUSES
            or self._should_cancel(run_id)
            or not self._run_state.consume_pending_node_rerun(run_id, node_id)
        ):
            return

        record.nodes[node_id].status = NodeStatus.PENDING
        record.nodes[node_id].finished_at = None
        self._run_state.runtime_state(run_id, node_id).next_scheduled_at = None
        remaining.add(node_id)
        await self._publish(run_id, "node_rerun_queued", node_id=node_id)
        await self.store.persist_run(run_id)

    async def _apply_fail_fast(
        self,
        *,
        run_id: str,
        pipeline: PipelineSpec,
        record: RunRecord,
        remaining: set[str],
    ) -> None:
        failed_nodes = {node_id for node_id, node in record.nodes.items() if node.status == NodeStatus.FAILED}
        if not pipeline.fail_fast or not failed_nodes:
            return
        for node_id in list(remaining):
            record.nodes[node_id].status = NodeStatus.SKIPPED
            record.nodes[node_id].finished_at = utcnow_iso()
            remaining.remove(node_id)
            await self._publish(run_id, "node_skipped", node_id=node_id, reason="fail_fast")

    async def _skip_blocked_nodes(
        self,
        *,
        run_id: str,
        node_map: dict[str, "NodeSpec"],
        record: RunRecord,
        remaining: set[str],
        cycle_state: _CycleState,
    ) -> None:
        blocked = self._blocked_nodes(
            remaining,
            node_map=node_map,
            record=record,
            cycle_state=cycle_state,
        )
        for node_id in blocked:
            node = node_map[node_id]
            skip_node, skip_reason = self._should_skip_node(node, record)
            record.nodes[node_id].status = NodeStatus.SKIPPED
            record.nodes[node_id].finished_at = utcnow_iso()
            remaining.remove(node_id)
            await self._publish(
                run_id,
                "node_skipped",
                node_id=node_id,
                reason=skip_reason if skip_node else "upstream_failure",
            )

    async def _finalize_settled_periodic_nodes(
        self,
        *,
        run_id: str,
        pipeline: PipelineSpec,
        node_map: dict[str, "NodeSpec"],
        record: RunRecord,
        remaining: set[str],
        periodic_scheduler: PeriodicScheduler,
    ) -> None:
        for node_id in list(remaining):
            node = node_map[node_id]
            if node.schedule is None:
                continue
            if any(record.nodes[dependency].status != NodeStatus.COMPLETED for dependency in node.depends_on):
                continue
            if not periodic_scheduler.fanout_group_settled(
                pipeline,
                record.nodes,
                node.schedule.until_fanout_settles_from,
            ):
                continue
            remaining.remove(node_id)
            await periodic_scheduler.finalize_node(run_id, node_id, reason="watched_group_settled")

    async def _queue_ready_nodes(
        self,
        *,
        remaining: set[str],
        ready: list[str],
        record: RunRecord,
        in_progress: dict[str, asyncio.Task[NodeExecutionOutcome]],
        launch: Callable[[str], asyncio.Future],
    ) -> None:
        for node_id in ready:
            if node_id in in_progress:
                continue
            remaining.remove(node_id)
            record.nodes[node_id].status = NodeStatus.QUEUED
            in_progress[node_id] = asyncio.create_task(launch(node_id))

    async def _launch_node(
        self,
        *,
        run_id: str,
        node_id: str,
        node_map: dict[str, "NodeSpec"],
        record: RunRecord,
        periodic_state: dict[str, PeriodicNodeRuntimeState],
        loop: asyncio.AbstractEventLoop,
    ) -> NodeExecutionOutcome:
        node = node_map[node_id]
        if node.schedule is None:
            return await self._execute_node(run_id, node_id)

        state = periodic_state[node_id]
        state.tick_count += 1
        tick_started_at = utcnow_iso()
        state.last_tick_started_at = tick_started_at
        state.last_tick_started_mono = loop.time()
        runtime_state = self._run_state.runtime_state(run_id, node_id)
        record.nodes[node_id].tick_count = state.tick_count
        runtime_state.last_tick_started_at = tick_started_at
        runtime_state.next_scheduled_at = None
        return await self._execute_node(
            run_id,
            node_id,
            periodic_tick_number=state.tick_count,
            periodic_tick_started_at=tick_started_at,
        )

    async def _drain_finished_tasks(
        self,
        *,
        run_id: str,
        in_progress: dict[str, asyncio.Task[NodeExecutionOutcome]],
        node_map: dict[str, "NodeSpec"],
        pipeline: PipelineSpec,
        record: RunRecord,
        periodic_scheduler: PeriodicScheduler,
        periodic_state: dict[str, PeriodicNodeRuntimeState],
        remaining: set[str],
        iteration_counts: dict[tuple[str, str], int],
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        done, _ = await asyncio.wait(in_progress.values(), timeout=0.1, return_when=asyncio.FIRST_COMPLETED)
        finished_ids = [node_id for node_id, task in in_progress.items() if task in done]
        for node_id in finished_ids:
            task = in_progress.pop(node_id)
            outcome = await task
            node = node_map[node_id]
            self._run_state.discard_node_cancel(run_id, node_id)

            if node.schedule is not None:
                await self._handle_periodic_completion(
                    run_id=run_id,
                    node_id=node_id,
                    node=node,
                    outcome=outcome,
                    pipeline=pipeline,
                    record=record,
                    periodic_scheduler=periodic_scheduler,
                    periodic_state=periodic_state,
                    remaining=remaining,
                    in_progress=in_progress,
                    loop=loop,
                )

            await self._handle_cycle_restart(
                run_id=run_id,
                node_id=node_id,
                node=node,
                pipeline=pipeline,
                node_map=node_map,
                record=record,
                iteration_counts=iteration_counts,
                remaining=remaining,
            )
            await self._handle_terminal_rerun(
                run_id=run_id,
                node_id=node_id,
                record=record,
                remaining=remaining,
            )

    async def _create_queued_run(
        self,
        pipeline: PipelineSpec,
        *,
        cancel_flag: threading.Event | None = None,
        optimization_parent_run_id: str | None = None,
        optimization_round: int | None = None,
        optimization_session: dict[str, Any] | None = None,
    ) -> RunRecord:
        run_id = self.store.new_run_id()
        self._initialize_run_tracking(run_id, cancel_flag=cancel_flag)
        run = RunRecord(
            id=run_id,
            status=RunStatus.QUEUED,
            pipeline=pipeline,
            optimization_parent_run_id=optimization_parent_run_id,
            optimization_round=optimization_round,
            optimization_session=deepcopy(optimization_session),
            nodes={node.id: NodeResult(node_id=node.id, status=NodeStatus.PENDING) for node in pipeline.nodes},
        )
        await self.store.create_run(run)
        await self._publish(run_id, "run_queued", pipeline=pipeline.model_dump(mode="json"))
        return run

    def _start_background(self, run_id: str, entrypoint: Callable[[], Any]) -> None:
        """Start a run thread; the thread owns the event loop for that run."""

        def _background() -> None:
            acquired = False
            try:
                while not acquired:
                    if self._should_cancel(run_id):
                        asyncio.run(self._finalize_cancelled_queue_run(run_id))
                        return
                    acquired = self._run_slots.acquire(timeout=0.1)
                asyncio.run(entrypoint())
            finally:
                if acquired:
                    self._run_slots.release()
                self._run_state.mark_finished(run_id)

        threading.Thread(target=_background, name=f"agentflow-{run_id}", daemon=True).start()

    async def _run_graph_optimization_session(self, parent_run_id: str) -> RunRecord:
        return await GraphOptimizationSession(
            store=self.store,
            create_queued_run=self._create_queued_run,
            run_child=self.run,
            publish=self._publish,
            should_cancel=self._should_cancel,
            run_cancel_flag=self._run_state.run_cancel_flag,
            mark_run_finished=self._run_state.mark_finished,
            clear_run_control_state=self._clear_run_control_state,
        ).run(parent_run_id)

    async def submit(self, pipeline: PipelineSpec) -> RunRecord:
        """Create a queued run and start its background scheduler when a slot opens.

        Returns the newly created `RunRecord` with all nodes initialized as pending.
        """
        optimization_session = None
        if pipeline.uses_graph_optimizer:
            optimization_session = {
                "kind": "graph",
                "optimizer": pipeline.optimizer,
                "total_rounds": pipeline.n_run,
                "current_round": 0,
                "child_run_ids": [],
                "latest_pipeline_path": None,
            }
        run = await self._create_queued_run(pipeline, optimization_session=optimization_session)
        if pipeline.uses_graph_optimizer:
            self._start_background(run.id, lambda: self._run_graph_optimization_session(run.id))
        else:
            self._start_background(run.id, lambda: self.run(run.id))
        return run

    async def wait(self, run_id: str, timeout: float | None = None) -> RunRecord:
        terminal = {RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED}

        async def _poll() -> RunRecord:
            while True:
                record = self.store.get_run(run_id)
                if record.status in terminal:
                    finished = self._run_state.run_finished_event(run_id)
                    if finished is None or finished.is_set():
                        return record
                await asyncio.sleep(0.05)

        if timeout is None:
            return await _poll()
        return await asyncio.wait_for(_poll(), timeout=timeout)

    async def cancel(self, run_id: str) -> RunRecord:
        """Request cancellation for a run.

        Queued runs are finalized immediately; active runs are marked cancelling and
        observed cooperatively by the run loop and executing nodes.
        """

        record = self.store.get_run(run_id)
        flag = self._run_state.run_cancel_flag(run_id)
        flag.set()
        await self.store.request_cancel(run_id)
        if record.status == RunStatus.QUEUED:
            await self._finalize_cancelled_queue_run(run_id)
            return self.store.get_run(run_id)
        if record.status in {RunStatus.RUNNING, RunStatus.PENDING}:
            record.status = RunStatus.CANCELLING
            await self._publish(run_id, "run_cancelling")
            await self.store.persist_run(run_id)
        return record

    async def rerun(self, run_id: str) -> RunRecord:
        """Submit a fresh run using the stored pipeline from an existing run.

        Returns the new queued `RunRecord`; prior run state is left unchanged.
        """

        record = self.store.get_run(run_id)
        return await self.submit(record.pipeline)

    async def resume(self, run_id: str) -> RunRecord:
        """Resume a failed/cancelled run, preserving completed node results.

        Creates a new run that copies completed node outputs and scratchboard
        from the original run. Failed/cancelled/skipped nodes are reset to
        pending so the pipeline continues from the point of failure.

        Returns the new queued ``RunRecord``.
        """
        old_record = self.store.get_run(run_id)
        if old_record.status not in {RunStatus.FAILED, RunStatus.CANCELLED}:
            raise ValueError(
                f"Can only resume failed or cancelled runs, but run `{run_id}` has status `{old_record.status.value}`"
            )

        new_run_id = self.store.new_run_id()
        new_run = build_resumed_run(old_record, new_run_id=new_run_id)

        self._initialize_run_tracking(new_run_id)
        await self.store.create_run(new_run)
        copy_resume_artifacts(self.store, source_run_id=run_id, resumed_run=new_run)
        await self._publish(new_run_id, "run_queued", pipeline=new_run.pipeline.model_dump(mode="json"), resumed_from=run_id)

        self._start_background(new_run_id, lambda: self.run(new_run_id))
        return new_run

    async def rerun_node(self, run_id: str, node_id: str) -> RunRecord:
        record = self.store.get_run(run_id)
        if node_id not in record.nodes:
            raise KeyError(f"Node `{node_id}` not found in run `{run_id}`.")

        if record.status in {RunStatus.RUNNING, RunStatus.PENDING}:
            if record.nodes[node_id].status not in _TERMINAL_NODE_STATUSES:
                raise ValueError(f"Node `{node_id}` is not in a terminal state.")
            self._run_state.queue_node_rerun(run_id, node_id)
            await self._publish(run_id, "node_rerun_requested", node_id=node_id)
            return record

        if record.status not in {RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED}:
            raise ValueError(f"Run `{run_id}` does not support node reruns in status `{record.status.value}`.")

        rerun_nodes = self._downstream_nodes(record.pipeline, node_id)
        new_run_id = self.store.new_run_id()
        new_run = build_rerun_node_run(record, new_run_id=new_run_id, rerun_nodes=rerun_nodes)
        self._initialize_run_tracking(new_run_id)
        await self.store.create_run(new_run)
        copy_resume_artifacts(self.store, source_run_id=run_id, resumed_run=new_run)
        await self._publish(
            new_run_id,
            "run_queued",
            pipeline=new_run.pipeline.model_dump(mode="json"),
            rerun_from=run_id,
            rerun_node=node_id,
        )
        self._start_background(new_run_id, lambda: self.run(new_run_id))
        return new_run

    def _should_cancel(self, run_id: str) -> bool:
        if self._run_state.run_cancel_flag(run_id).is_set():
            return True
        return self.store.cancel_requested(run_id)

    def _should_cancel_node(self, run_id: str, node_id: str) -> bool:
        return self._run_state.should_cancel_node(run_id, node_id)

    async def _finalize_cancelled_queue_run(self, run_id: str) -> None:
        record = finalize_cancelled_queued_run(self.store.get_run(run_id))
        await self._publish(run_id, "run_completed", status=record.status.value)
        await self.store.clear_cancel_request(run_id)
        await self.store.persist_run(run_id)

    async def _publish(self, run_id: str, event_type: str, *, node_id: str | None = None, **data: Any) -> None:
        await self.store.append_event(run_id, RunEvent(run_id=run_id, type=event_type, node_id=node_id, data=data))

    async def _execute_node(
        self,
        run_id: str,
        node_id: str,
        *,
        periodic_tick_number: int | None = None,
        periodic_tick_started_at: str | None = None,
    ) -> NodeExecutionOutcome:
        return await self._node_executor().execute(
            run_id,
            node_id,
            periodic_tick_number=periodic_tick_number,
            periodic_tick_started_at=periodic_tick_started_at,
        )

    async def run(self, run_id: str) -> RunRecord:
        """Drive a run until all nodes reach terminal outcomes.

        The loop skips nodes blocked by upstream failure, queues nodes whose
        dependencies are satisfied, and bounds concurrent execution with a
        semaphore. `_execute_node()` handles per-node retry attempts; this loop
        handles scheduling, completion collection, and explicit reruns. Periodic
        nodes execute as repeated ticks, can emit cancel/rerun actions for a watched
        fanout, reschedule on `every_seconds`, and finalize once that fanout group
        has fully settled.
        """

        record = self.store.get_run(run_id)
        pipeline = record.pipeline
        record.status = RunStatus.RUNNING
        record.started_at = utcnow_iso()
        await self._publish(run_id, "run_started", pipeline=pipeline.model_dump(mode="json"))
        await self.store.persist_run(run_id)

        node_map = pipeline.node_map
        iteration_counts: dict[tuple[str, str], int] = {}

        # Create scratchboard if enabled
        if pipeline.scratchboard:
            self.scratchboards.create_for_run(self.store.base_dir, run_id)

        # Exclude nodes already in a terminal state (e.g. completed from a resumed run)
        remaining = {
            node_id for node_id in node_map
            if record.nodes[node_id].status not in {NodeStatus.COMPLETED}
        }
        in_progress: dict[str, asyncio.Task[NodeExecutionOutcome]] = {}
        semaphore = asyncio.Semaphore(pipeline.concurrency)
        loop = asyncio.get_running_loop()
        periodic_scheduler = self._periodic_scheduler()
        periodic_state = {
            node_id: PeriodicNodeRuntimeState()
            for node_id, node in node_map.items()
            if node.schedule is not None
        }

        async def launch(node_id: str) -> NodeExecutionOutcome:
            async with semaphore:
                return await self._launch_node(
                    run_id=run_id,
                    node_id=node_id,
                    node_map=node_map,
                    record=record,
                    periodic_state=periodic_state,
                    loop=loop,
                )

        while remaining or in_progress:
            if self._should_cancel(run_id):
                for node_id in list(remaining):
                    await self._mark_node_cancelled(run_id, node_id, "run_cancelled")
                    remaining.remove(node_id)
                if not in_progress:
                    break

            await self._apply_fail_fast(
                run_id=run_id,
                pipeline=pipeline,
                record=record,
                remaining=remaining,
            )
            cycle_state = self._compute_cycle_state(run_id, pipeline, node_map, record, iteration_counts)
            await self._skip_blocked_nodes(
                run_id=run_id,
                node_map=node_map,
                record=record,
                remaining=remaining,
                cycle_state=cycle_state,
            )
            await self._finalize_settled_periodic_nodes(
                run_id=run_id,
                pipeline=pipeline,
                node_map=node_map,
                record=record,
                remaining=remaining,
                periodic_scheduler=periodic_scheduler,
            )

            now = loop.time()
            ready = self._ready_node_ids(
                remaining,
                in_progress=in_progress,
                now=now,
                node_map=node_map,
                record=record,
                cycle_state=cycle_state,
                periodic_state=periodic_state,
            )
            for node_id in list(ready):
                node = node_map[node_id]
                skip_node, skip_reason = self._should_skip_node(node, record)
                if skip_node:
                    record.nodes[node_id].status = NodeStatus.SKIPPED
                    record.nodes[node_id].finished_at = utcnow_iso()
                    remaining.remove(node_id)
                    await self._publish(run_id, "node_skipped", node_id=node_id, reason=skip_reason or "skip_if")
                    await self.store.persist_run(run_id)
                    ready.remove(node_id)
                    continue
            await self._queue_ready_nodes(
                remaining=remaining,
                ready=ready,
                record=record,
                in_progress=in_progress,
                launch=launch,
            )
            if in_progress:
                await self._drain_finished_tasks(
                    run_id=run_id,
                    in_progress=in_progress,
                    node_map=node_map,
                    pipeline=pipeline,
                    record=record,
                    periodic_scheduler=periodic_scheduler,
                    periodic_state=periodic_state,
                    remaining=remaining,
                    iteration_counts=iteration_counts,
                    loop=loop,
                )
            elif remaining:
                await asyncio.sleep(0.05)
            else:
                break

        if record.status == RunStatus.CANCELLING or self._should_cancel(run_id):
            record.status = RunStatus.CANCELLED
        elif any(node.status == NodeStatus.FAILED for node in record.nodes.values()):
            record.status = RunStatus.FAILED
        else:
            record.status = RunStatus.COMPLETED
        record.finished_at = utcnow_iso()
        await self._publish(run_id, "run_completed", status=record.status.value)
        await self.store.clear_cancel_request(run_id)
        await self.store.persist_run(run_id)
        self._clear_run_control_state(run_id)
        return record

    @staticmethod
    def _downstream_nodes(pipeline: PipelineSpec, start_node_id: str) -> set[str]:
        reverse_edges: dict[str, list[str]] = {}
        for node in pipeline.nodes:
            for dep in node.depends_on:
                reverse_edges.setdefault(dep, []).append(node.id)

        pending = [start_node_id]
        seen: set[str] = set()
        while pending:
            current = pending.pop()
            if current in seen:
                continue
            seen.add(current)
            pending.extend(reverse_edges.get(current, []))
        return seen
