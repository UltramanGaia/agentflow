from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from server.api.schemas.graph_view import GraphExportView, GraphImportRequest, GraphUpsertRequest, GraphValidateRequest
from server.api.services.graph_service import GraphService

router = APIRouter(prefix="/api/graphs", tags=["graphs"])


def _service(request: Request) -> GraphService:
    return request.app.state.graph_service


@router.get("")
def list_graphs(request: Request) -> list[dict]:
    return [item.model_dump(mode="json") for item in _service(request).list_graphs()]


@router.post("")
def create_graph(request: Request, payload: GraphUpsertRequest) -> dict:
    graph = _service(request).save_graph(payload.pipeline, graph_id=payload.graph_id, layout=payload.layout)
    return graph.model_dump(mode="json")


@router.post("/validate")
def validate_graph(request: Request, payload: GraphValidateRequest) -> dict:
    pipeline = _service(request).validate_graph(payload.pipeline)
    return {"valid": True, "pipeline": pipeline.model_dump(mode="json")}


@router.post("/import")
def import_graph(request: Request, payload: GraphImportRequest) -> dict:
    try:
        pipeline = _service(request).import_graph_from_path(payload.path)
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"pipeline": pipeline}


@router.get("/{graph_id}")
def get_graph(graph_id: str, request: Request) -> dict:
    try:
        return _service(request).get_graph(graph_id).model_dump(mode="json")
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"Graph `{graph_id}` not found.") from exc


@router.put("/{graph_id}")
def update_graph(graph_id: str, request: Request, payload: GraphUpsertRequest) -> dict:
    graph = _service(request).save_graph(payload.pipeline, graph_id=graph_id, layout=payload.layout)
    return graph.model_dump(mode="json")


@router.get("/{graph_id}/export/python", response_model=GraphExportView)
def export_graph_python(graph_id: str, request: Request) -> GraphExportView:
    try:
        filename, content = _service(request).export_graph_to_python(graph_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"Graph `{graph_id}` not found.") from exc
    return GraphExportView(graph_id=graph_id, filename=filename, content=content)
