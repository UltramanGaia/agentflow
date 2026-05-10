from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

from server.api.services.run_service import RunService

router = APIRouter(prefix="/api/runs/{run_id}/nodes/{node_id}/artifacts", tags=["artifacts"])


def _service(request: Request) -> RunService:
    return request.app.state.run_service


@router.get("")
def list_artifacts(run_id: str, node_id: str, request: Request) -> list[dict]:
    try:
        return [item.model_dump(mode="json") for item in _service(request).list_node_artifacts(run_id, node_id)]
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Run `{run_id}` not found.") from exc


@router.get("/{name:path}")
def get_artifact(run_id: str, node_id: str, name: str, request: Request) -> FileResponse:
    try:
        path = _service(request).artifact_path(run_id, node_id, name)
    except (KeyError, FileNotFoundError) as exc:
        raise HTTPException(status_code=404, detail=f"Artifact `{name}` not found.") from exc
    return FileResponse(path)
