from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class RunNodeArtifactView(BaseModel):
    name: str
    size: int


class RunNodeView(BaseModel):
    id: str
    agent: str
    prompt: str
    depends_on: list[str] = Field(default_factory=list)
    status: str
    started_at: str | None = None
    finished_at: str | None = None
    exit_code: int | None = None
    final_response: str | None = None
    output: str | None = None
    artifacts: list[RunNodeArtifactView] = Field(default_factory=list)


class RunEdgeView(BaseModel):
    id: str
    source: str
    target: str


class RunGraphView(BaseModel):
    nodes: list[RunNodeView]
    edges: list[RunEdgeView]


class RunSummaryView(BaseModel):
    id: str
    status: str
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None
    pipeline_name: str
    node_count: int
    failed_nodes: list[str] = Field(default_factory=list)


class RunDetailView(BaseModel):
    run: dict[str, Any]
    graph: RunGraphView
    events: list[dict[str, Any]]


class RunSubmitRequest(BaseModel):
    graph_id: str | None = None
    pipeline: dict[str, Any] | None = None
    pipeline_path: str | None = None


class RunValidateRequest(BaseModel):
    pipeline: dict[str, Any] | None = None
    pipeline_path: str | None = None


class RunActionResponse(BaseModel):
    run: dict[str, Any]
    redirected_run_id: str | None = None
