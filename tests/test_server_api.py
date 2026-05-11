from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from agentflow.specs import NodeResult, NodeStatus, PipelineSpec, RunRecord, RunStatus
from server.api.app import create_app


def _sample_pipeline(name: str = "demo-pipeline") -> dict:
    return {
        "name": name,
        "working_dir": ".",
        "nodes": [
            {"id": "plan", "agent": "codex", "prompt": "Plan the work.", "depends_on": []},
            {"id": "apply", "agent": "codex", "prompt": "Apply the plan.", "depends_on": ["plan"]},
        ],
    }


def _write_run_fixture(runs_dir: Path) -> str:
    run = RunRecord(
        id="run-api-1",
        status=RunStatus.FAILED,
        pipeline=PipelineSpec.model_validate(_sample_pipeline()),
        nodes={
            "plan": NodeResult(node_id="plan", status=NodeStatus.COMPLETED, output="ok"),
            "apply": NodeResult(node_id="apply", status=NodeStatus.FAILED, output="boom", exit_code=1),
        },
    )
    run_dir = runs_dir / run.id
    run_dir.mkdir(parents=True)
    (run_dir / "run.json").write_text(run.model_dump_json(indent=2), encoding="utf-8")
    (run_dir / "events.jsonl").write_text(
        json.dumps({"run_id": run.id, "type": "node_failed", "node_id": "apply", "data": {"exit_code": 1}}) + "\n",
        encoding="utf-8",
    )
    artifact_dir = run_dir / "artifacts" / "apply"
    artifact_dir.mkdir(parents=True)
    (artifact_dir / "stderr.log").write_text("boom\n", encoding="utf-8")
    return run.id


def test_graph_crud_and_export(tmp_path: Path) -> None:
    workspace = tmp_path / ".agentflow"
    client = TestClient(create_app(workspace_dir=workspace, allow_pipeline_path=True))

    created = client.post("/api/graphs", json={"pipeline": _sample_pipeline(), "layout": {"plan": {"x": 1, "y": 2}}})
    assert created.status_code == 200
    graph_id = created.json()["meta"]["id"]

    listed = client.get("/api/graphs")
    assert listed.status_code == 200
    assert listed.json()[0]["id"] == graph_id

    exported = client.get(f"/api/graphs/{graph_id}/export/python")
    assert exported.status_code == 200
    assert "with Graph(" in exported.json()["content"]


def test_runs_endpoints_read_persisted_runs(tmp_path: Path) -> None:
    workspace = tmp_path / ".agentflow"
    runs_dir = workspace / "runs"
    runs_dir.mkdir(parents=True)
    run_id = _write_run_fixture(runs_dir)

    client = TestClient(create_app(workspace_dir=workspace, runs_dir=runs_dir))

    listing = client.get("/api/runs")
    assert listing.status_code == 200
    assert listing.json()[0]["id"] == run_id

    detail = client.get(f"/api/runs/{run_id}")
    assert detail.status_code == 200
    assert detail.json()["graph"]["nodes"][1]["artifacts"][0]["name"] == "stderr.log"

    events = client.get(f"/api/runs/{run_id}/events")
    assert events.status_code == 200
    assert events.json()[0]["type"] == "node_failed"


def test_web_shell_served_from_dist(tmp_path: Path) -> None:
    workspace = tmp_path / ".agentflow"
    web_dir = tmp_path / "web"
    dist_dir = web_dir / "dist"
    dist_dir.mkdir(parents=True)
    (dist_dir / "index.html").write_text("<!doctype html><title>AgentFlow Server</title><div id='root'></div>", encoding="utf-8")

    client = TestClient(create_app(workspace_dir=workspace, web_dir=web_dir))

    root = client.get("/")
    assert root.status_code == 200
    assert "AgentFlow Server" in root.text

    nested = client.get("/runs")
    assert nested.status_code == 200
    assert "AgentFlow Server" in nested.text


def test_rerun_node_creates_new_run_for_terminal_run(tmp_path: Path) -> None:
    workspace = tmp_path / ".agentflow"
    runs_dir = workspace / "runs"
    runs_dir.mkdir(parents=True)
    run_id = _write_run_fixture(runs_dir)

    client = TestClient(create_app(workspace_dir=workspace, runs_dir=runs_dir))

    response = client.post(f"/api/runs/{run_id}/rerun-node/apply")
    assert response.status_code == 200
    payload = response.json()
    assert payload["redirected_run_id"]
    new_run = client.get(f"/api/runs/{payload['redirected_run_id']}").json()["run"]
    assert new_run["nodes"]["plan"]["status"] == "completed"
