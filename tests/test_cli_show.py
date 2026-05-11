from pathlib import Path

from agentflow.cli import app
from agentflow.specs import NodeResult, NodeSpec, NodeStatus, PipelineSpec, RunRecord, RunStatus
from typer.testing import CliRunner


def _write_run_fixture(runs_dir: Path) -> str:
    run_id = "run-123"
    run_dir = runs_dir / run_id
    run_dir.mkdir(parents=True)

    record = RunRecord(
        id=run_id,
        status=RunStatus.FAILED,
        started_at="2026-05-10T15:39:31.000000+00:00",
        finished_at="2026-05-10T15:40:29.000000+00:00",
        pipeline=PipelineSpec(
            name="example-pipeline",
            nodes=[
                NodeSpec(
                    id="scan",
                    agent="gaia",
                    prompt="Scan the repo.",
                )
            ],
        ),
        nodes={
            "scan": NodeResult(
                node_id="scan",
                status=NodeStatus.FAILED,
                exit_code=1,
                output="API Error: 403 quota exceeded",
            )
        },
    )
    (run_dir / "run.json").write_text(record.model_dump_json(indent=2), encoding="utf-8")
    return run_id


def test_show_summary_output_reads_run_artifacts(tmp_path: Path) -> None:
    run_id = _write_run_fixture(tmp_path)
    runner = CliRunner()

    result = runner.invoke(app, ["show", run_id, "--runs-dir", str(tmp_path), "--output", "summary"])

    assert result.exit_code == 0
    assert f"Run {run_id}: failed" in result.output
    assert "scan [gaia]: failed" in result.output
    assert "Diagnosis:" in result.output


def test_show_json_summary_output_reads_run_artifacts(tmp_path: Path) -> None:
    run_id = _write_run_fixture(tmp_path)
    runner = CliRunner()

    result = runner.invoke(app, ["show", run_id, "--runs-dir", str(tmp_path), "--output", "json-summary"])

    assert result.exit_code == 0
    assert '"id": "run-123"' in result.output
    assert '"diagnosis": "Gaia reached the provider' in result.output
