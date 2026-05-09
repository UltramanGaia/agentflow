from __future__ import annotations

import asyncio
from copy import deepcopy
import json
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable

from agentflow.graph_optimizer import (
    GRAPH_OPTIMIZER_MAX_ATTEMPTS,
    GENERATED_PIPELINE_EDITED_FILENAME,
    GENERATED_PIPELINE_FILENAME,
    GENERATED_PIPELINE_ORIGINAL_FILENAME,
    GRAPH_REPORT_FILENAME,
    OPTIMIZER_PROMPT_FILENAME,
    OPTIMIZER_RESULT_FILENAME,
    OPTIMIZER_VALIDATION_FILENAME,
    build_graph_report,
    copy_run_traces,
    optimizer_failure_summary,
    render_graph_optimizer_prompt,
    write_editable_pipeline_python,
    write_optimizer_result,
    write_validation_result,
)
from agentflow.loader import load_pipeline_from_path
from agentflow.specs import PipelineSpec, RunRecord, RunStatus, builtin_agent_kind
from agentflow.store import RunStore
from agentflow.tuned_agents import _parse_agent_output, _run_optimizer
from agentflow.utils import ensure_dir, utcnow_iso


CreateQueuedRun = Callable[..., Awaitable[RunRecord]]
PublishEvent = Callable[..., Awaitable[None]]
RunChild = Callable[[str], Awaitable[RunRecord]]


async def run_optimizer_in_thread(
    optimizer_kind: Any,
    *,
    prompt: str,
    repo_dir: Path,
    runtime_dir: Path,
    env: dict[str, str] | None = None,
) -> Any:
    # Keep accepting `env` for older call sites; optimizer execution currently
    # derives its environment from the prepared local agent invocation.
    del env
    return await asyncio.to_thread(
        _run_optimizer,
        optimizer_kind,
        prompt=prompt,
        repo_dir=repo_dir,
        runtime_dir=runtime_dir,
    )


@dataclass(slots=True)
class GraphOptimizationSession:
    store: RunStore
    create_queued_run: CreateQueuedRun
    run_child: RunChild
    publish: PublishEvent
    should_cancel: Callable[[str], bool]
    run_cancel_flag: Callable[[str], threading.Event]
    mark_run_finished: Callable[[str], None]
    clear_run_control_state: Callable[[str], None]

    def _round_dir(self, parent_run_id: str, round_number: int) -> Path:
        return ensure_dir(self.store.run_dir(parent_run_id) / "optimization" / f"round-{round_number:03d}")

    async def _fail(self, parent_run_id: str, *, error: str, round_number: int, round_dir: Path) -> RunRecord:
        record = self.store.get_run(parent_run_id)
        record.status = RunStatus.FAILED
        record.finished_at = utcnow_iso()
        write_validation_result(round_dir / OPTIMIZER_VALIDATION_FILENAME, ok=False, error=error)
        await self.publish(
            parent_run_id,
            "optimization_failed",
            round_number=round_number,
            error=error,
            round_dir=str(round_dir),
        )
        await self.publish(parent_run_id, "run_completed", status=record.status.value)
        await self.store.clear_cancel_request(parent_run_id)
        await self.store.persist_run(parent_run_id)
        self.clear_run_control_state(parent_run_id)
        return record

    async def run(self, parent_run_id: str) -> RunRecord:
        parent = self.store.get_run(parent_run_id)
        optimizer_name = parent.pipeline.optimizer or ""
        optimizer_kind = builtin_agent_kind(optimizer_name)
        if optimizer_kind is None:
            return await self._fail(
                parent_run_id,
                error=f"invalid optimizer `{optimizer_name}`",
                round_number=0,
                round_dir=self.store.run_dir(parent_run_id),
            )

        parent.status = RunStatus.RUNNING
        parent.started_at = utcnow_iso()
        await self.publish(parent_run_id, "run_started", pipeline=parent.pipeline.model_dump(mode="json"))
        await self.store.persist_run(parent_run_id)

        optimization_session = dict(parent.optimization_session or {})
        optimization_session.setdefault("kind", "graph")
        optimization_session.setdefault("optimizer", optimizer_name)
        optimization_session.setdefault("total_rounds", parent.pipeline.n_run)
        optimization_session.setdefault("current_round", 0)
        optimization_session.setdefault("child_run_ids", [])
        optimization_session.setdefault("latest_pipeline_path", None)
        parent.optimization_session = optimization_session

        current_pipeline = parent.pipeline
        final_child: RunRecord | None = None

        for round_number in range(1, current_pipeline.n_run + 1):
            if self.should_cancel(parent_run_id):
                break

            round_dir = self._round_dir(parent_run_id, round_number)
            pipeline_path = round_dir / GENERATED_PIPELINE_FILENAME
            write_editable_pipeline_python(pipeline_path, current_pipeline)
            write_editable_pipeline_python(round_dir / GENERATED_PIPELINE_ORIGINAL_FILENAME, current_pipeline)

            optimization_session["current_round"] = round_number
            optimization_session["latest_pipeline_path"] = str(pipeline_path)
            parent.optimization_session = optimization_session
            parent.pipeline = current_pipeline
            await self.publish(
                parent_run_id,
                "optimization_round_started",
                round_number=round_number,
                total_rounds=current_pipeline.n_run,
                round_dir=str(round_dir),
            )
            await self.store.persist_run(parent_run_id)

            child_pipeline = current_pipeline.model_copy(update={"optimizer": None, "n_run": 1})
            child = await self.create_queued_run(
                child_pipeline,
                cancel_flag=self.run_cancel_flag(parent_run_id),
                optimization_parent_run_id=parent_run_id,
                optimization_round=round_number,
            )
            optimization_session["child_run_ids"].append(child.id)
            parent.optimization_session = optimization_session
            await self.publish(
                parent_run_id,
                "optimization_child_run_created",
                round_number=round_number,
                child_run_id=child.id,
            )
            await self.store.persist_run(parent_run_id)

            try:
                final_child = await self.run_child(child.id)
            finally:
                self.mark_run_finished(child.id)

            parent.nodes = deepcopy(final_child.nodes)
            parent.pipeline = current_pipeline
            await self.publish(
                parent_run_id,
                "optimization_round_completed",
                round_number=round_number,
                child_run_id=final_child.id,
                child_status=final_child.status.value,
            )

            traces_dir = ensure_dir(round_dir / "traces")
            copied_traces = copy_run_traces(final_child, self.store, traces_dir)
            graph_report = build_graph_report(
                parent_run_id=parent_run_id,
                round_number=round_number,
                total_rounds=current_pipeline.n_run,
                run=final_child,
                store=self.store,
                copied_traces=copied_traces,
            )
            (round_dir / GRAPH_REPORT_FILENAME).write_text(
                json.dumps(graph_report, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            await self.store.persist_run(parent_run_id)

            if round_number >= current_pipeline.n_run or self.should_cancel(parent_run_id):
                continue

            failure_summary: str | None = None
            loaded_pipeline: PipelineSpec | None = None
            optimizer_result: Any | None = None
            for attempt_number in range(1, GRAPH_OPTIMIZER_MAX_ATTEMPTS + 1):
                attempt_dir = ensure_dir(round_dir / "attempts" / f"attempt-{attempt_number:03d}")
                prompt = render_graph_optimizer_prompt(
                    optimizer=optimizer_name,
                    pipeline_path=pipeline_path,
                    graph_report_path=round_dir / GRAPH_REPORT_FILENAME,
                    traces_dir=traces_dir,
                    round_number=round_number,
                    total_rounds=current_pipeline.n_run,
                    attempt_number=attempt_number,
                    max_attempts=GRAPH_OPTIMIZER_MAX_ATTEMPTS,
                    previous_failure=failure_summary,
                )
                (attempt_dir / OPTIMIZER_PROMPT_FILENAME).write_text(prompt, encoding="utf-8")
                (round_dir / OPTIMIZER_PROMPT_FILENAME).write_text(prompt, encoding="utf-8")
                await self.publish(
                    parent_run_id,
                    "optimization_optimizer_started",
                    round_number=round_number,
                    optimizer=optimizer_name,
                    attempt_number=attempt_number,
                    max_attempts=GRAPH_OPTIMIZER_MAX_ATTEMPTS,
                )
                optimizer_result = await run_optimizer_in_thread(
                    optimizer_kind,
                    prompt=prompt,
                    repo_dir=round_dir,
                    runtime_dir=attempt_dir / "optimizer-runtime",
                )
                write_optimizer_result(
                    attempt_dir / OPTIMIZER_RESULT_FILENAME,
                    command=optimizer_result.command,
                    exit_code=optimizer_result.exit_code,
                    stdout=optimizer_result.stdout,
                    stderr=optimizer_result.stderr,
                )
                write_optimizer_result(
                    round_dir / OPTIMIZER_RESULT_FILENAME,
                    command=optimizer_result.command,
                    exit_code=optimizer_result.exit_code,
                    stdout=optimizer_result.stdout,
                    stderr=optimizer_result.stderr,
                )
                if pipeline_path.exists():
                    edited_text = pipeline_path.read_text(encoding="utf-8")
                    (attempt_dir / GENERATED_PIPELINE_EDITED_FILENAME).write_text(edited_text, encoding="utf-8")
                    (round_dir / GENERATED_PIPELINE_EDITED_FILENAME).write_text(edited_text, encoding="utf-8")
                if optimizer_result.exit_code != 0:
                    failure_summary = optimizer_failure_summary(
                        "Optimizer",
                        exit_code=optimizer_result.exit_code,
                        stdout=optimizer_result.stdout,
                        stderr=optimizer_result.stderr,
                    )
                    write_validation_result(attempt_dir / OPTIMIZER_VALIDATION_FILENAME, ok=False, error=failure_summary)
                    write_validation_result(round_dir / OPTIMIZER_VALIDATION_FILENAME, ok=False, error=failure_summary)
                else:
                    try:
                        loaded_pipeline = load_pipeline_from_path(pipeline_path)
                    except Exception as exc:
                        failure_summary = optimizer_failure_summary(
                            "Optimized pipeline",
                            error=f"optimized pipeline failed to load: {exc}",
                        )
                        write_validation_result(
                            attempt_dir / OPTIMIZER_VALIDATION_FILENAME,
                            ok=False,
                            error=failure_summary,
                        )
                        write_validation_result(
                            round_dir / OPTIMIZER_VALIDATION_FILENAME,
                            ok=False,
                            error=failure_summary,
                        )
                    else:
                        write_validation_result(attempt_dir / OPTIMIZER_VALIDATION_FILENAME, ok=True)
                        write_validation_result(round_dir / OPTIMIZER_VALIDATION_FILENAME, ok=True)
                        break

                if attempt_number < GRAPH_OPTIMIZER_MAX_ATTEMPTS:
                    await self.publish(
                        parent_run_id,
                        "optimization_optimizer_retrying",
                        round_number=round_number,
                        attempt_number=attempt_number,
                        error=failure_summary,
                    )

            if loaded_pipeline is None:
                return await self._fail(
                    parent_run_id,
                    error=failure_summary or "optimizer failed to produce a valid pipeline",
                    round_number=round_number,
                    round_dir=round_dir,
                )

            current_pipeline = loaded_pipeline.model_copy(
                update={"optimizer": optimizer_name, "n_run": parent.pipeline.n_run}
            )
            parent.pipeline = current_pipeline
            await self.publish(
                parent_run_id,
                "optimization_pipeline_accepted",
                round_number=round_number,
                attempt_number=attempt_number,
                optimizer_output=_parse_agent_output(
                    optimizer_kind,
                    f"graph_optimizer_{parent_run_id}_{round_number}",
                    optimizer_result.stdout,
                ),
            )
            await self.store.persist_run(parent_run_id)

        if self.should_cancel(parent_run_id):
            parent.status = RunStatus.CANCELLED
        elif final_child is None:
            parent.status = RunStatus.FAILED
        elif final_child.status == RunStatus.CANCELLED:
            parent.status = RunStatus.CANCELLED
        elif final_child.status == RunStatus.FAILED:
            parent.status = RunStatus.FAILED
        else:
            parent.status = RunStatus.COMPLETED

        parent.finished_at = utcnow_iso()
        await self.publish(parent_run_id, "run_completed", status=parent.status.value)
        await self.store.clear_cancel_request(parent_run_id)
        await self.store.persist_run(parent_run_id)
        self.clear_run_control_state(parent_run_id)
        return parent
