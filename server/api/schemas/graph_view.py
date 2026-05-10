from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class GraphNodePosition(BaseModel):
    x: float = 0
    y: float = 0


class GraphMetaView(BaseModel):
    id: str
    name: str
    description: str | None = None
    created_at: str
    updated_at: str
    layout: dict[str, GraphNodePosition] = Field(default_factory=dict)


class GraphSummaryView(BaseModel):
    id: str
    name: str
    description: str | None = None
    updated_at: str
    node_count: int


class GraphView(BaseModel):
    meta: GraphMetaView
    pipeline: dict[str, Any]


class GraphUpsertRequest(BaseModel):
    graph_id: str | None = None
    pipeline: dict[str, Any]
    layout: dict[str, GraphNodePosition] = Field(default_factory=dict)


class GraphValidateRequest(BaseModel):
    pipeline: dict[str, Any]


class GraphImportRequest(BaseModel):
    path: str


class GraphExportView(BaseModel):
    graph_id: str
    filename: str
    content: str
