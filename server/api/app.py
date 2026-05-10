from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from agentflow.orchestrator import Orchestrator
from agentflow.store import RunStore
from server.api.routes.artifacts import router as artifacts_router
from server.api.routes.graphs import router as graphs_router
from server.api.routes.runs import router as runs_router
from server.api.services.graph_service import GraphService
from server.api.services.run_service import RunService


def create_app(
    *,
    workspace_dir: str | Path = ".agentflow",
    runs_dir: str | Path | None = None,
    max_concurrent_runs: int = 2,
    allow_pipeline_path: bool | None = None,
) -> FastAPI:
    workspace_path = Path(workspace_dir).expanduser()
    runs_path = Path(runs_dir).expanduser() if runs_dir is not None else workspace_path / "runs"
    graph_service = GraphService(workspace_path)
    store = RunStore(runs_path)
    orchestrator = Orchestrator(store=store, max_concurrent_runs=max_concurrent_runs)

    app = FastAPI(title="AgentFlow Server", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.state.workspace_dir = workspace_path
    app.state.graph_service = graph_service
    app.state.store = store
    app.state.orchestrator = orchestrator
    app.state.run_service = RunService(
        store=store,
        orchestrator=orchestrator,
        graph_service=graph_service,
        allow_pipeline_path=(
            os.getenv("AGENTFLOW_API_ALLOW_PIPELINE_PATH", "").strip() == "1"
            if allow_pipeline_path is None
            else allow_pipeline_path
        ),
    )

    app.include_router(graphs_router)
    app.include_router(runs_router)
    app.include_router(artifacts_router)

    web_dir = Path(__file__).resolve().parents[1] / "web"
    app.mount("/static", StaticFiles(directory=web_dir), name="static")

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/")
    def root() -> FileResponse:
        return FileResponse(web_dir / "index.html")

    @app.get("/{full_path:path}")
    def spa(full_path: str) -> FileResponse:
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not found")
        return FileResponse(web_dir / "index.html")

    return app
