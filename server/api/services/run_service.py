from __future__ import annotations

from pathlib import Path
from typing import Any

from agentflow.loader import load_pipeline_from_data, load_pipeline_from_path
from agentflow.orchestrator import Orchestrator
from agentflow.specs import NodeStatus, RunRecord
from agentflow.store import RunStore
from server.api.schemas.run_view import (
    RunActionResponse,
    RunNodeAttemptView,
    RunDetailView,
    RunEdgeView,
    RunGraphView,
    RunNodeArtifactView,
    RunNodeView,
    RunSummaryView,
)
from server.api.services.graph_service import GraphService


class RunService:
    def __init__(
        self,
        *,
        store: RunStore,
        orchestrator: Orchestrator,
        graph_service: GraphService,
        allow_pipeline_path: bool = False,
    ) -> None:
        self.store = store
        self.orchestrator = orchestrator
        self.graph_service = graph_service
        self.allow_pipeline_path = allow_pipeline_path

    def list_runs(self) -> list[RunSummaryView]:
        runs = []
        for record in self.store.list_runs():
            failed_nodes = [node_id for node_id, node in record.nodes.items() if node.status == NodeStatus.FAILED]
            runs.append(
                RunSummaryView(
                    id=record.id,
                    status=record.status.value,
                    created_at=record.created_at,
                    started_at=record.started_at,
                    finished_at=record.finished_at,
                    pipeline_name=record.pipeline.name,
                    node_count=len(record.pipeline.nodes),
                    failed_nodes=failed_nodes,
                )
            )
        return runs

    def get_run_detail(self, run_id: str) -> RunDetailView:
        record = self.store.get_run(run_id)
        return RunDetailView(
            run=record.model_dump(mode="json"),
            graph=self._build_graph(record),
            events=[event.model_dump(mode="json") for event in self.store.get_events(run_id)],
        )

    def list_node_artifacts(self, run_id: str, node_id: str) -> list[RunNodeArtifactView]:
        artifact_dir = Path(self.store.base_dir) / run_id / "artifacts" / node_id
        if not artifact_dir.exists():
            return []
        return [
            RunNodeArtifactView(name=path.name, size=path.stat().st_size)
            for path in sorted(artifact_dir.iterdir())
            if path.is_file()
        ]

    def artifact_path(self, run_id: str, node_id: str, name: str) -> Path:
        path = Path(self.store.base_dir) / run_id / "artifacts" / node_id / name
        if not path.is_file():
            raise FileNotFoundError(name)
        return path

    def validate_submission(self, *, pipeline: dict[str, Any] | None, pipeline_path: str | None):
        if pipeline is not None:
            return load_pipeline_from_data(pipeline)
        if pipeline_path:
            if not self.allow_pipeline_path:
                raise PermissionError("`pipeline_path` is disabled for the web API.")
            return load_pipeline_from_path(pipeline_path)
        raise ValueError("Provide `pipeline` or `pipeline_path`.")

    async def submit(self, *, graph_id: str | None, pipeline: dict[str, Any] | None, pipeline_path: str | None) -> RunActionResponse:
        if graph_id:
            pipeline = self.graph_service.get_graph(graph_id).pipeline
        spec = self.validate_submission(pipeline=pipeline, pipeline_path=pipeline_path)
        run = await self.orchestrator.submit(spec)
        return RunActionResponse(run=run.model_dump(mode="json"))

    async def cancel(self, run_id: str) -> RunActionResponse:
        run = await self.orchestrator.cancel(run_id)
        return RunActionResponse(run=run.model_dump(mode="json"))

    async def resume(self, run_id: str) -> RunActionResponse:
        run = await self.orchestrator.resume(run_id)
        return RunActionResponse(run=run.model_dump(mode="json"), redirected_run_id=run.id)

    async def rerun(self, run_id: str) -> RunActionResponse:
        run = await self.orchestrator.rerun(run_id)
        return RunActionResponse(run=run.model_dump(mode="json"), redirected_run_id=run.id)

    async def rerun_node(self, run_id: str, node_id: str) -> RunActionResponse:
        run = await self.orchestrator.rerun_node(run_id, node_id)
        redirected = run.id if run.id != run_id else None
        return RunActionResponse(run=run.model_dump(mode="json"), redirected_run_id=redirected)

    def _build_graph(self, record: RunRecord) -> RunGraphView:
        fanout_group_by_node = {
            member_id: group_id
            for group_id, member_ids in record.pipeline.fanouts.items()
            for member_id in member_ids
        }
        nodes = [
            RunNodeView(
                id=node.id,
                agent=node.agent.value if hasattr(node.agent, "value") else str(node.agent),
                prompt=node.prompt,
                depends_on=list(node.depends_on),
                fanout_group=node.fanout_group or fanout_group_by_node.get(node.id),
                fanout_member=dict(node.fanout_member) if node.fanout_member else (
                    {"node_id": node.id} if (node.fanout_group or fanout_group_by_node.get(node.id)) else None
                ),
                status=record.nodes[node.id].status.value,
                started_at=record.nodes[node.id].started_at,
                finished_at=record.nodes[node.id].finished_at,
                exit_code=record.nodes[node.id].exit_code,
                final_response=record.nodes[node.id].final_response,
                output=record.nodes[node.id].output,
                tick_count=record.nodes[node.id].tick_count,
                attempts=[
                    RunNodeAttemptView(
                        number=attempt.number,
                        status=attempt.status.value,
                        started_at=attempt.started_at,
                        finished_at=attempt.finished_at,
                        exit_code=attempt.exit_code,
                        success=attempt.success,
                        success_details=list(attempt.success_details),
                    )
                    for attempt in record.nodes[node.id].attempts
                ],
                artifacts=self.list_node_artifacts(record.id, node.id),
            )
            for node in record.pipeline.nodes
        ]
        edges = [
            RunEdgeView(id=f"{dep}->{node.id}", source=dep, target=node.id)
            for node in record.pipeline.nodes
            for dep in node.depends_on
        ]
        return RunGraphView(nodes=nodes, edges=edges)
