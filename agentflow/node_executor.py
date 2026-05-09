from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from agentflow.agents.registry import AdapterRegistry
from agentflow.context import render_node_prompt
from agentflow.launch_artifacts import launch_artifact_payload
from agentflow.periodic import PeriodicActionEnvelope, parse_periodic_actions
from agentflow.prepared import ExecutionPaths, build_execution_paths
from agentflow.runtime_state import NodeRuntimeState
from agentflow.runner import Runner
from agentflow.scratchboard_manager import ScratchboardManager
from agentflow.specs_core import NodeStatus, PeriodicActuationMode
from agentflow.specs_models import NodeAttempt
from agentflow.store import RunStore
from agentflow.success import evaluate_success
from agentflow.tuned_agents import resolve_node_for_execution
from agentflow.traces import create_trace_parser
from agentflow.utils import utcnow_iso
from agentflow.worktree_manager import WorktreeManager


PublishEvent = Callable[..., Awaitable[None]]


@dataclass(slots=True)
class NodeExecutionOutcome:
    node_id: str
    periodic_tick_number: int | None = None
    periodic_actions: PeriodicActionEnvelope | None = None
    periodic_action_parse_error: str | None = None


@dataclass(slots=True)
class NodeExecutor:
    store: RunStore
    adapters: AdapterRegistry
    runner: Runner
    worktrees: WorktreeManager
    scratchboards: ScratchboardManager
    publish: PublishEvent
    node_runtime_state: Callable[[str, str], NodeRuntimeState]
    runtime_states_for_run: Callable[[str], dict[str, NodeRuntimeState]]
    should_cancel: Callable[[str], bool]
    should_cancel_node: Callable[[str, str], bool]

    def _build_paths(self, run_id: str, node_id: str, node_target: Any, pipeline_workdir) -> ExecutionPaths:
        return build_execution_paths(
            base_dir=self.store.base_dir,
            pipeline_workdir=pipeline_workdir,
            run_id=run_id,
            node_id=node_id,
            node_target=node_target,
        )

    async def _publish_trace(self, run_id: str, node_id: str, event) -> None:
        await self.store.append_artifact_text(run_id, node_id, "trace.jsonl", event.model_dump_json() + "\n")
        await self.publish(run_id, "node_trace", node_id=node_id, trace=event.model_dump(mode="json"))

    async def _write_launch_artifacts(self, run_id: str, node_id: str, attempt_number: int, plan: Any) -> None:
        payload = launch_artifact_payload(attempt_number, plan)
        await self.store.write_artifact_json(run_id, node_id, "launch.json", payload)
        await self.store.write_artifact_json(run_id, node_id, f"launch-attempt-{attempt_number}.json", payload)

    async def _mark_node_cancelled(self, run_id: str, node_id: str, reason: str) -> None:
        record = self.store.get_run(run_id)
        result = record.nodes[node_id]
        result.status = NodeStatus.CANCELLED
        result.finished_at = utcnow_iso()
        if reason == "run_cancelled":
            await self.store.append_artifact_text(run_id, node_id, "stderr.log", "Cancelled by user\n")
        await self.publish(run_id, "node_cancelled", node_id=node_id, reason=reason)

    async def execute(
        self,
        run_id: str,
        node_id: str,
        *,
        periodic_tick_number: int | None = None,
        periodic_tick_started_at: str | None = None,
    ) -> NodeExecutionOutcome:
        """Execute one node from prompt preparation through final persisted result."""

        record = self.store.get_run(run_id)
        pipeline = record.pipeline
        node = pipeline.node_map[node_id]
        result = record.nodes[node_id]
        runtime_state = self.node_runtime_state(run_id, node_id)
        runtime_state.stdout_lines = []
        runtime_state.stderr_lines = []
        runtime_state.trace_events = []
        runtime_state.current_attempt = 0
        result.started_at = result.started_at or (periodic_tick_started_at or utcnow_iso())
        if periodic_tick_number is not None:
            result.tick_count = max(result.tick_count, periodic_tick_number)
            runtime_state.last_tick_started_at = periodic_tick_started_at
        result.status = NodeStatus.RUNNING
        await self.publish(run_id, "node_started", node_id=node_id)
        if periodic_tick_number is not None:
            await self.publish(
                run_id,
                "node_tick_started",
                node_id=node_id,
                tick_number=periodic_tick_number,
                tick_started_at=periodic_tick_started_at,
            )

        prompt = render_node_prompt(
            pipeline,
            node,
            record.nodes,
            runtime_states=self.runtime_states_for_run(run_id),
            run_id=run_id,
            artifacts_base_dir=self.store.base_dir,
            current_tick_number=periodic_tick_number,
            current_tick_started_at=periodic_tick_started_at,
        )
        execution_resolution = resolve_node_for_execution(node, pipeline.working_path)
        execution_node = execution_resolution.node
        runtime_agent = execution_resolution.runtime_agent
        prepared_worktree = self.worktrees.prepare_node(pipeline, execution_node, run_id=run_id)
        execution_node = prepared_worktree.node
        if prepared_worktree.warning is not None:
            await self.publish(
                run_id,
                "node_trace",
                node_id=node_id,
                trace={"kind": "warning", "title": prepared_worktree.warning},
            )

        paths = self._build_paths(run_id, node_id, execution_node.target, pipeline.working_path)

        prompt += self.scratchboards.prompt_suffix_for_run(run_id)
        adapter = self.adapters.get(runtime_agent)
        parser = create_trace_parser(runtime_agent, node.id)
        periodic_actions: PeriodicActionEnvelope | None = None
        periodic_action_parse_error: str | None = None

        for attempt_number in range(1, node.retries + 2):
            if self.should_cancel(run_id):
                await self._mark_node_cancelled(run_id, node_id, "run_cancelled")
                return NodeExecutionOutcome(node_id=node_id, periodic_tick_number=periodic_tick_number)

            attempt = NodeAttempt(number=attempt_number, status=NodeStatus.RUNNING, started_at=utcnow_iso())
            attempt_stdout_lines: list[str] = []
            attempt_stderr_lines: list[str] = []
            runtime_state.current_attempt = attempt_number
            result.attempts.append(attempt)
            parser.start_attempt(attempt_number)
            prepared = adapter.prepare(execution_node, prompt, paths)
            plan = self.runner.plan_execution(execution_node, prepared, paths)
            await self._write_launch_artifacts(run_id, node_id, attempt_number, plan)
            await self.store.append_artifact_text(
                run_id,
                node_id,
                "stdout.log",
                f"\n=== attempt {attempt_number} started {attempt.started_at} ===\n",
            )
            await self.store.append_artifact_text(
                run_id,
                node_id,
                "stderr.log",
                f"\n=== attempt {attempt_number} started {attempt.started_at} ===\n",
            )
            if attempt_number > 1:
                result.status = NodeStatus.RETRYING
                await self.publish(
                    run_id,
                    "node_retrying",
                    node_id=node_id,
                    attempt=attempt_number,
                    max_attempts=node.retries + 1,
                )
                result.status = NodeStatus.RUNNING

            async def on_output(stream_name: str, line: str) -> None:
                if stream_name == "stdout":
                    await self.store.append_artifact_text(run_id, node_id, "stdout.log", line + "\n")
                    parsed_events = parser.feed(line)
                    if parsed_events or parser.supports_raw_stdout_fallback():
                        attempt_stdout_lines.append(line)
                        runtime_state.stdout_lines = attempt_stdout_lines
                    for event in parsed_events:
                        runtime_state.trace_events.append(event)
                        await self._publish_trace(run_id, node_id, event)
                else:
                    attempt_stderr_lines.append(line)
                    runtime_state.stderr_lines = attempt_stderr_lines
                    await self.store.append_artifact_text(run_id, node_id, "stderr.log", line + "\n")
                    event = parser.emit("stderr", "stderr", line, line, source="stderr")
                    runtime_state.trace_events.append(event)
                    await self._publish_trace(run_id, node_id, event)

            raw = await self.runner.execute(
                execution_node,
                prepared,
                paths,
                on_output,
                lambda: self.should_cancel(run_id) or self.should_cancel_node(run_id, node_id),
            )
            result.exit_code = raw.exit_code
            runtime_state.stdout_lines = attempt_stdout_lines
            runtime_state.stderr_lines = attempt_stderr_lines
            result.final_response = parser.finalize()
            if not result.final_response and parser.supports_raw_stdout_fallback():
                result.final_response = "\n".join(attempt_stdout_lines).strip()
            result.output = result.final_response if execution_node.capture.value == "final" else "\n".join(attempt_stdout_lines)
            success_ok, success_details = evaluate_success(execution_node, result, paths.host_workdir)
            result.success = success_ok
            result.success_details = success_details
            attempt.finished_at = utcnow_iso()
            attempt.exit_code = raw.exit_code
            attempt.final_response = result.final_response
            attempt.output = result.output
            attempt.success = success_ok
            attempt.success_details = success_details

            if raw.cancelled or self.should_cancel(run_id):
                attempt.status = NodeStatus.CANCELLED
                result.status = NodeStatus.CANCELLED
                result.finished_at = attempt.finished_at
                await self.publish(
                    run_id,
                    "node_cancelled",
                    node_id=node_id,
                    attempt=attempt_number,
                    exit_code=raw.exit_code,
                )
                break

            if raw.exit_code == 0 and success_ok:
                attempt.status = NodeStatus.COMPLETED
                result.status = NodeStatus.READY if periodic_tick_number is not None else NodeStatus.COMPLETED
                result.finished_at = attempt.finished_at
                if periodic_tick_number is not None:
                    if execution_node.schedule and execution_node.schedule.actuation == PeriodicActuationMode.OUTPUT_JSON:
                        periodic_actions, periodic_action_parse_error = parse_periodic_actions(result.final_response)
                        if periodic_actions is not None and periodic_actions.analysis is not None:
                            result.output = periodic_actions.analysis
                            attempt.output = result.output
                    await self.publish(
                        run_id,
                        "node_tick_completed",
                        node_id=node_id,
                        tick_number=periodic_tick_number,
                        attempt=attempt_number,
                        exit_code=result.exit_code,
                        success=result.success,
                        output=result.output,
                        final_response=result.final_response,
                        success_details=result.success_details,
                    )
                else:
                    await self.publish(
                        run_id,
                        "node_completed",
                        node_id=node_id,
                        attempt=attempt_number,
                        exit_code=result.exit_code,
                        success=result.success,
                        output=result.output,
                        final_response=result.final_response,
                        success_details=result.success_details,
                    )
                break

            attempt.status = NodeStatus.FAILED
            result.status = NodeStatus.FAILED
            result.finished_at = attempt.finished_at
            await self.publish(
                run_id,
                "node_failed",
                node_id=node_id,
                attempt=attempt_number,
                exit_code=result.exit_code,
                success=result.success,
                output=result.output,
                final_response=result.final_response,
                success_details=result.success_details,
            )
            if attempt_number <= node.retries:
                if getattr(node, "retry_backoff_strategy", "exponential") == "exponential":
                    delay = min(
                        node.retry_backoff_seconds * (2 ** (attempt_number - 1)),
                        getattr(node, "retry_backoff_max_seconds", 300.0),
                    )
                else:
                    delay = node.retry_backoff_seconds * attempt_number
                await asyncio.sleep(max(delay, 0.0))
                continue
            break

        await self.store.write_artifact_text(run_id, node_id, "output.txt", result.output or "")
        await self.store.write_artifact_json(run_id, node_id, "result.json", result.model_dump(mode="json"))

        await self.scratchboards.merge_output(run_id, node_id, result.output)

        if pipeline.use_worktree:
            diff = self.worktrees.capture_diff_and_cleanup(prepared_worktree.lease)
            if diff:
                await self.store.write_artifact_text(run_id, node_id, "diff.patch", diff)
            result.diff = diff

        await self.store.persist_run(run_id)
        if periodic_tick_number is not None:
            return NodeExecutionOutcome(
                node_id=node_id,
                periodic_tick_number=periodic_tick_number,
                periodic_actions=periodic_actions,
                periodic_action_parse_error=periodic_action_parse_error,
            )
        return NodeExecutionOutcome(node_id=node_id)
