from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from uuid import uuid4

from agentflow.loader import load_pipeline_from_data, load_pipeline_from_path
from agentflow.specs import PipelineSpec
from agentflow.utils import ensure_dir, utcnow_iso
from server.api.schemas.graph_view import GraphMetaView, GraphSummaryView, GraphView


_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slugify(value: str) -> str:
    normalized = _SLUG_RE.sub("-", value.strip().lower()).strip("-")
    return normalized or uuid4().hex[:8]


class GraphService:
    def __init__(self, workspace_dir: str | Path = ".agentflow") -> None:
        self.workspace_dir = ensure_dir(Path(workspace_dir).expanduser())
        self.graphs_dir = ensure_dir(self.workspace_dir / "graphs")

    def list_graphs(self) -> list[GraphSummaryView]:
        items: list[GraphSummaryView] = []
        for graph_dir in self.graphs_dir.iterdir():
            if not graph_dir.is_dir():
                continue
            meta = self._read_meta(graph_dir.name)
            pipeline = self._read_pipeline(graph_dir.name)
            items.append(
                GraphSummaryView(
                    id=meta.id,
                    name=meta.name,
                    description=meta.description,
                    updated_at=meta.updated_at,
                    node_count=len(pipeline.nodes),
                )
            )
        return sorted(items, key=lambda item: item.updated_at, reverse=True)

    def get_graph(self, graph_id: str) -> GraphView:
        meta = self._read_meta(graph_id)
        pipeline = self._read_pipeline(graph_id)
        return GraphView(meta=meta, pipeline=pipeline.model_dump(mode="json"))

    def save_graph(
        self,
        pipeline_payload: dict[str, Any],
        *,
        graph_id: str | None = None,
        layout: dict[str, Any] | None = None,
    ) -> GraphView:
        pipeline = load_pipeline_from_data(pipeline_payload)
        resolved_id = graph_id or _slugify(pipeline.name)
        graph_dir = ensure_dir(self.graphs_dir / resolved_id)
        now = utcnow_iso()
        existing_meta = self._try_read_meta(resolved_id)
        meta = GraphMetaView(
            id=resolved_id,
            name=pipeline.name,
            description=pipeline.description,
            created_at=existing_meta.created_at if existing_meta is not None else now,
            updated_at=now,
            layout=self._normalize_layout(layout or (existing_meta.layout if existing_meta is not None else {})),
        )
        (graph_dir / "graph.json").write_text(
            json.dumps(pipeline.model_dump(mode="json"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (graph_dir / "meta.json").write_text(meta.model_dump_json(indent=2), encoding="utf-8")
        return GraphView(meta=meta, pipeline=pipeline.model_dump(mode="json"))

    def validate_graph(self, pipeline_payload: dict[str, Any]) -> PipelineSpec:
        return load_pipeline_from_data(pipeline_payload)

    def import_graph_from_path(self, path: str) -> dict[str, Any]:
        pipeline = load_pipeline_from_path(path)
        return pipeline.model_dump(mode="json")

    def export_graph_to_python(self, graph_id: str) -> tuple[str, str]:
        graph = self.get_graph(graph_id)
        pipeline = PipelineSpec.model_validate(graph.pipeline)
        return f"{graph.meta.id}.py", self._pipeline_to_python(pipeline)

    def _graph_dir(self, graph_id: str) -> Path:
        graph_dir = self.graphs_dir / graph_id
        if not graph_dir.is_dir():
            raise FileNotFoundError(graph_id)
        return graph_dir

    def _read_pipeline(self, graph_id: str) -> PipelineSpec:
        graph_path = self._graph_dir(graph_id) / "graph.json"
        return PipelineSpec.model_validate_json(graph_path.read_text(encoding="utf-8"))

    def _read_meta(self, graph_id: str) -> GraphMetaView:
        meta = self._try_read_meta(graph_id)
        if meta is None:
            raise FileNotFoundError(graph_id)
        return meta

    def _try_read_meta(self, graph_id: str) -> GraphMetaView | None:
        graph_dir = self.graphs_dir / graph_id
        meta_path = graph_dir / "meta.json"
        if not meta_path.exists():
            graph_path = graph_dir / "graph.json"
            if not graph_dir.is_dir() or not graph_path.exists():
                return None
            pipeline = self._read_pipeline(graph_id)
            now = utcnow_iso()
            return GraphMetaView(
                id=graph_id,
                name=pipeline.name,
                description=pipeline.description,
                created_at=now,
                updated_at=now,
                layout={},
            )
        return GraphMetaView.model_validate_json(meta_path.read_text(encoding="utf-8"))

    def _normalize_layout(self, layout: dict[str, Any]) -> dict[str, Any]:
        normalized: dict[str, Any] = {}
        for node_id, position in layout.items():
            if hasattr(position, "model_dump"):
                payload = position.model_dump(mode="json")
            elif isinstance(position, dict):
                payload = position
            else:
                continue
            normalized[node_id] = {
                "x": float(payload.get("x", 0)),
                "y": float(payload.get("y", 0)),
            }
        return normalized

    def _pipeline_to_python(self, pipeline: PipelineSpec) -> str:
        graph_kwargs = {
            "description": pipeline.description,
            "working_dir": pipeline.working_dir,
            "optimizer": pipeline.optimizer,
            "n_run": pipeline.n_run,
            "concurrency": pipeline.concurrency,
            "fail_fast": pipeline.fail_fast,
            "max_iterations": pipeline.max_iterations,
            "scratchboard": pipeline.scratchboard,
            "use_worktree": pipeline.use_worktree,
            "node_defaults": pipeline.node_defaults.model_dump(mode="json") if pipeline.node_defaults else None,
            "agent_defaults": pipeline.agent_defaults,
            "local_target_defaults": pipeline.local_target_defaults.model_dump(mode="json") if pipeline.local_target_defaults else None,
        }
        lines = ["from agentflow import Graph, agent", "", "", f"with Graph({pipeline.name!r},"]
        for key, value in graph_kwargs.items():
            if value is None:
                continue
            lines.append(f"    {key}={value!r},")
        lines.append(") as g:")
        lines.append("    nodes = {}")
        for node in pipeline.nodes:
            payload = node.model_dump(mode="json")
            payload.pop("id", None)
            payload.pop("depends_on", None)
            prompt = payload.pop("prompt")
            agent_name = payload.pop("agent")
            lines.append(
                f"    nodes[{node.id!r}] = agent({agent_name!r}, task_id={node.id!r}, prompt={prompt!r}, **{payload!r})"
            )
        for node in pipeline.nodes:
            for dep in node.depends_on:
                lines.append(f"    nodes[{dep!r}] >> nodes[{node.id!r}]")
            for restart_target in node.on_failure_restart:
                lines.append(f"    nodes[{node.id!r}].on_failure >> nodes[{restart_target!r}]")
        lines.extend(["", "print(g.to_json())", ""])
        return "\n".join(lines)
