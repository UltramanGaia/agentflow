import asyncio
from pathlib import Path
import sys

import click

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import agentflow.cli as cli_module
from agentflow.cli import OutputFormat, _run_pipeline, app
from agentflow.specs import NodeResult, NodeSpec, NodeStatus, PipelineSpec, RunEvent, RunRecord, RunStatus
from agentflow.store import RunStore
import pytest
from typer.testing import CliRunner


def _build_pipeline() -> PipelineSpec:
    return PipelineSpec(
        name="streaming-pipeline",
        nodes=[NodeSpec(id="scan", agent="shell", prompt="echo hi")],
    )


def _build_run_record(run_id: str, pipeline: PipelineSpec) -> RunRecord:
    return RunRecord(
        id=run_id,
        status=RunStatus.COMPLETED,
        pipeline=pipeline,
        started_at="2026-05-11T00:00:00+00:00",
        finished_at="2026-05-11T00:00:01+00:00",
        nodes={
            "scan": NodeResult(
                node_id="scan",
                status=NodeStatus.COMPLETED,
                output="done",
                final_response="done",
                exit_code=0,
            )
        },
    )


class FakeOrchestrator:
    def __init__(self, store: RunStore, completed: RunRecord) -> None:
        self.store = store
        self.completed = completed

    async def submit(self, pipeline: PipelineSpec) -> RunRecord:
        return RunRecord(
            id=self.completed.id,
            status=RunStatus.RUNNING,
            pipeline=pipeline,
            nodes={"scan": NodeResult(node_id="scan", status=NodeStatus.RUNNING)},
        )

    async def wait(self, run_id: str, timeout: float | None = None) -> RunRecord:
        await self.store.append_event(
            run_id,
            RunEvent(
                run_id=run_id,
                type="node_trace",
                node_id="scan",
                data={"trace": {"node_id": "scan", "source": "stdout", "content": "hello stdout"}},
            ),
        )
        await self.store.append_event(
            run_id,
            RunEvent(
                run_id=run_id,
                type="node_trace",
                node_id="scan",
                data={"trace": {"node_id": "scan", "source": "stderr", "content": "hello stderr"}},
            ),
        )
        await asyncio.sleep(0.15)
        return self.completed


def test_run_help_includes_tee_node_output() -> None:
    runner = CliRunner()

    result = runner.invoke(app, ["run", "--help"])

    assert result.exit_code == 0
    assert "tee-node-output" in result.stdout
    assert "Also print node" in result.stdout


def test_run_pipeline_tee_node_output_streams_stdout_and_stderr(tmp_path: Path, monkeypatch, capsys) -> None:
    pipeline = _build_pipeline()
    completed = _build_run_record("run-stream-summary", pipeline)
    store = RunStore(tmp_path / "runs")
    orchestrator = FakeOrchestrator(store, completed)

    monkeypatch.setattr(cli_module, "_build_runtime", lambda runs_dir, max_concurrent_runs: (store, orchestrator))

    with pytest.raises(click.exceptions.Exit) as exc_info:
        _run_pipeline(
            pipeline,
            str(tmp_path / "runs"),
            2,
            OutputFormat.SUMMARY,
            tee_node_output=True,
        )

    captured = capsys.readouterr()
    assert exc_info.value.exit_code == 0
    assert "[scan] hello stdout" in captured.out
    assert "[scan stderr] hello stderr" in captured.err
    assert "Run run-stream-summary: completed" in captured.out


def test_run_pipeline_tee_node_output_preserves_json_stdout(tmp_path: Path, monkeypatch, capsys) -> None:
    pipeline = _build_pipeline()
    completed = _build_run_record("run-stream-json", pipeline)
    store = RunStore(tmp_path / "runs")
    orchestrator = FakeOrchestrator(store, completed)

    monkeypatch.setattr(cli_module, "_build_runtime", lambda runs_dir, max_concurrent_runs: (store, orchestrator))

    with pytest.raises(click.exceptions.Exit) as exc_info:
        _run_pipeline(
            pipeline,
            str(tmp_path / "runs"),
            2,
            OutputFormat.JSON,
            tee_node_output=True,
        )

    captured = capsys.readouterr()
    assert exc_info.value.exit_code == 0
    assert "[scan] hello stdout" not in captured.out
    assert '"id": "run-stream-json"' in captured.out
    assert "[scan] hello stdout" in captured.err
    assert "[scan stderr] hello stderr" in captured.err
