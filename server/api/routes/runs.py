from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from server.api.schemas.run_view import RunSubmitRequest, RunValidateRequest
from server.api.services.event_stream import stream_run_events
from server.api.services.run_service import RunService

router = APIRouter(prefix="/api/runs", tags=["runs"])


def _service(request: Request) -> RunService:
    return request.app.state.run_service


@router.get("")
def list_runs(request: Request) -> list[dict]:
    return [item.model_dump(mode="json") for item in _service(request).list_runs()]


@router.post("")
async def create_run(request: Request, payload: RunSubmitRequest) -> dict:
    try:
        response = await _service(request).submit(
            graph_id=payload.graph_id,
            pipeline=payload.pipeline,
            pipeline_path=payload.pipeline_path,
        )
    except (ValueError, PermissionError, OSError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return response.model_dump(mode="json")


@router.post("/validate")
def validate_run_submission(request: Request, payload: RunValidateRequest) -> dict:
    try:
        pipeline = _service(request).validate_submission(
            pipeline=payload.pipeline,
            pipeline_path=payload.pipeline_path,
        )
    except (ValueError, PermissionError, OSError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"valid": True, "pipeline": pipeline.model_dump(mode="json")}


@router.get("/{run_id}")
def get_run(run_id: str, request: Request) -> dict:
    try:
        return _service(request).get_run_detail(run_id).model_dump(mode="json")
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Run `{run_id}` not found.") from exc


@router.get("/{run_id}/events")
def get_run_events(run_id: str, request: Request) -> list[dict]:
    try:
        detail = _service(request).get_run_detail(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Run `{run_id}` not found.") from exc
    return detail.events


@router.get("/{run_id}/stream")
async def get_run_stream(run_id: str, request: Request) -> StreamingResponse:
    try:
        request.app.state.store.get_run(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Run `{run_id}` not found.") from exc
    return StreamingResponse(stream_run_events(request.app.state.store, run_id), media_type="text/event-stream")


@router.post("/{run_id}/cancel")
async def cancel_run(run_id: str, request: Request) -> dict:
    try:
        response = await _service(request).cancel(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Run `{run_id}` not found.") from exc
    return response.model_dump(mode="json")


@router.post("/{run_id}/resume")
async def resume_run(run_id: str, request: Request) -> dict:
    try:
        response = await _service(request).resume(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Run `{run_id}` not found.") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return response.model_dump(mode="json")


@router.post("/{run_id}/rerun")
async def rerun_run(run_id: str, request: Request) -> dict:
    try:
        response = await _service(request).rerun(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Run `{run_id}` not found.") from exc
    return response.model_dump(mode="json")


@router.post("/{run_id}/rerun-node/{node_id}")
async def rerun_node(run_id: str, node_id: str, request: Request) -> dict:
    try:
        response = await _service(request).rerun_node(run_id, node_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return response.model_dump(mode="json")
