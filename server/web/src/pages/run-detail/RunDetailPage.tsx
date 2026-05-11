import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import ReactFlow, { Background, Controls, MarkerType, Position, type Edge, type Node, type NodeTypes } from "reactflow";
import { useNavigate, useParams } from "react-router-dom";
import { AgentNode } from "../../components/graph/AgentNode";
import { ErrorState, LoadingState } from "../../components/feedback/States";
import { StatusBadge } from "../../components/status/StatusBadge";
import { getRunDetail, cancelRun, rerunNode, rerunRun, resumeRun } from "../../features/runs/api";
import { useRunStream } from "../../features/run-viewer/sse";
import { requestText } from "../../lib/http";
import type { RunNode } from "../../types/api";

const nodeTypes: NodeTypes = { agentNode: AgentNode };

const NODE_WIDTH = 220;
const NODE_HEIGHT = 132;
const COLUMN_GAP = 120;
const ROW_GAP = 44;
const PADDING_X = 80;
const PADDING_Y = 80;

function buildRunLayout(runNodes: RunNode[]): Node[] {
  const nodeById = new Map(runNodes.map((node) => [node.id, node]));
  const layerById = new Map<string, number>();
  const indegree = new Map<string, number>();
  const downstream = new Map<string, string[]>();
  const order = new Map(runNodes.map((node, index) => [node.id, index]));

  runNodes.forEach((node) => {
    indegree.set(node.id, 0);
    downstream.set(node.id, []);
  });

  runNodes.forEach((node) => {
    node.depends_on.forEach((dependency) => {
      if (!nodeById.has(dependency)) {
        return;
      }
      indegree.set(node.id, (indegree.get(node.id) ?? 0) + 1);
      downstream.get(dependency)?.push(node.id);
    });
  });

  const queue = runNodes
    .filter((node) => (indegree.get(node.id) ?? 0) === 0)
    .sort((left, right) => (order.get(left.id) ?? 0) - (order.get(right.id) ?? 0))
    .map((node) => node.id);
  const topoOrder: string[] = [];

  while (queue.length > 0) {
    const currentId = queue.shift()!;
    topoOrder.push(currentId);
    const currentLayer = layerById.get(currentId) ?? 0;
    for (const nextId of downstream.get(currentId) ?? []) {
      layerById.set(nextId, Math.max(layerById.get(nextId) ?? 0, currentLayer + 1));
      indegree.set(nextId, (indegree.get(nextId) ?? 1) - 1);
      if ((indegree.get(nextId) ?? 0) === 0) {
        queue.push(nextId);
        queue.sort((left, right) => (order.get(left) ?? 0) - (order.get(right) ?? 0));
      }
    }
  }

  const remainingIds = runNodes
    .map((node) => node.id)
    .filter((nodeId) => !topoOrder.includes(nodeId))
    .sort((left, right) => (order.get(left) ?? 0) - (order.get(right) ?? 0));
  topoOrder.push(...remainingIds);

  remainingIds.forEach((nodeId) => {
    const node = nodeById.get(nodeId);
    if (!node) {
      return;
    }
    const inferredLayer = node.depends_on.reduce((maxLayer, dependency) => {
      return Math.max(maxLayer, (layerById.get(dependency) ?? -1) + 1);
    }, 0);
    layerById.set(nodeId, Math.max(layerById.get(nodeId) ?? 0, inferredLayer));
  });

  const columns = new Map<number, string[]>();
  topoOrder.forEach((nodeId) => {
    const layer = layerById.get(nodeId) ?? 0;
    const nodesInColumn = columns.get(layer) ?? [];
    nodesInColumn.push(nodeId);
    columns.set(layer, nodesInColumn);
  });

  const maxColumnSize = Math.max(...Array.from(columns.values(), (column) => column.length), 1);

  return runNodes.map<Node>((node) => {
    const layer = layerById.get(node.id) ?? 0;
    const row = columns.get(layer)?.indexOf(node.id) ?? 0;
    const columnSize = columns.get(layer)?.length ?? 1;
    const verticalOffset = ((maxColumnSize - columnSize) * (NODE_HEIGHT + ROW_GAP)) / 2;

    return {
      id: node.id,
      type: "agentNode",
      position: {
        x: PADDING_X + layer * (NODE_WIDTH + COLUMN_GAP),
        y: PADDING_Y + verticalOffset + row * (NODE_HEIGHT + ROW_GAP),
      },
      sourcePosition: Position.Right,
      targetPosition: Position.Left,
      data: {
        title: node.id,
        agent: node.agent,
        status: node.status,
      },
      selected: false,
    };
  });
}

export function RunDetailPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { runId } = useParams();
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<"overview" | "events" | "stdout" | "stderr" | "artifacts">("overview");
  useRunStream(runId);
  const runQuery = useQuery({
    queryKey: ["run-detail", runId],
    queryFn: () => getRunDetail(runId!),
    enabled: Boolean(runId),
    refetchInterval: 15_000,
  });

  const actionMutation = useMutation({
    mutationFn: async (action: "cancel" | "resume" | "rerun") => {
      if (!runId) {
        throw new Error("Missing run id");
      }
      if (action === "cancel") {
        return cancelRun(runId);
      }
      if (action === "resume") {
        return resumeRun(runId);
      }
      return rerunRun(runId);
    },
    onSuccess: async (payload) => {
      const nextRunId = payload.redirected_run_id ?? payload.run.id;
      await queryClient.invalidateQueries({ queryKey: ["runs"] });
      await queryClient.invalidateQueries({ queryKey: ["run-detail", runId] });
      if (nextRunId && nextRunId !== runId) {
        navigate(`/runs/${nextRunId}`);
      }
    },
  });

  const rerunNodeMutation = useMutation({
    mutationFn: async (nodeId: string) => rerunNode(runId!, nodeId),
    onSuccess: async (payload) => {
      const nextRunId = payload.redirected_run_id ?? payload.run.id;
      await queryClient.invalidateQueries({ queryKey: ["runs"] });
      if (nextRunId) {
        navigate(`/runs/${nextRunId}`);
      }
    },
  });

  const selectedNode = useMemo(() => {
    const detail = runQuery.data;
    if (!detail) {
      return null;
    }
    return detail.graph.nodes.find((node) => node.id === selectedNodeId) ?? detail.graph.nodes[0] ?? null;
  }, [runQuery.data, selectedNodeId]);

  const logQuery = useQuery({
    queryKey: ["run-log", runId, selectedNode?.id, activeTab],
    queryFn: () =>
      requestText(
        `/api/runs/${runId}/nodes/${selectedNode?.id}/artifacts/${activeTab === "stdout" ? "stdout.log" : "stderr.log"}`,
      ),
    enabled:
      Boolean(runId && selectedNode?.id) &&
      (activeTab === "stdout" || activeTab === "stderr") &&
      Boolean(selectedNode?.artifacts.some((artifact) => artifact.name === `${activeTab}.log`)),
  });

  if (runQuery.isLoading) {
    return <LoadingState>Loading run detail...</LoadingState>;
  }
  if (runQuery.error) {
    return <ErrorState message={runQuery.error.message} />;
  }
  if (!runQuery.data) {
    return <ErrorState message="Run detail not found." />;
  }

  const detail = runQuery.data;
  const nodes = buildRunLayout(detail.graph.nodes).map((node) => ({
    ...node,
    selected: node.id === selectedNode?.id,
  }));
  const edges = detail.graph.edges.map<Edge>((edge) => ({
    ...edge,
    type: "smoothstep",
    markerEnd: {
      type: MarkerType.ArrowClosed,
      width: 22,
      height: 22,
    },
  }));

  return (
    <div className="layout">
      <section className="panel stack">
        <div className="section-head">
          <div>
            <h2>{detail.run.pipeline.name}</h2>
            <div className="muted">{detail.run.id}</div>
          </div>
          <div className="row-wrap">
            <StatusBadge status={detail.run.status} />
            <button className="button danger" onClick={() => actionMutation.mutate("cancel")} type="button">
              Cancel
            </button>
            <button className="button" onClick={() => actionMutation.mutate("resume")} type="button">
              Resume
            </button>
            <button className="button" onClick={() => actionMutation.mutate("rerun")} type="button">
              Rerun
            </button>
          </div>
        </div>
        <div className="flow-panel">
          <ReactFlow
            fitView
            edges={edges}
            nodes={nodes}
            nodeTypes={nodeTypes}
            nodesConnectable={false}
            nodesDraggable={false}
            onNodeClick={(_, node) => setSelectedNodeId(node.id)}
            proOptions={{ hideAttribution: true }}
          >
            <Background gap={24} />
            <Controls showInteractive={false} />
          </ReactFlow>
        </div>
      </section>
      <section className="panel stack">
        <div className="tabs">
          {(["overview", "events", "stdout", "stderr", "artifacts"] as const).map((tab) => (
            <button
              className={`tab${activeTab === tab ? " active" : ""}`}
              key={tab}
              onClick={() => setActiveTab(tab)}
              type="button"
            >
              {tab === "events" ? "Trace" : tab[0].toUpperCase() + tab.slice(1)}
            </button>
          ))}
        </div>
        {activeTab === "overview" ? (
          <div className="list">
            {detail.graph.nodes.map((node) => (
              <div className="list-item" key={node.id}>
                <div className="section-head compact">
                  <button className="button" onClick={() => setSelectedNodeId(node.id)} type="button">
                    {node.id}
                  </button>
                  <StatusBadge status={node.status} />
                </div>
                <div className="muted">{node.agent}</div>
                <div className="row-wrap">
                  <button className="button" onClick={() => rerunNodeMutation.mutate(node.id)} type="button">
                    Rerun Node
                  </button>
                </div>
              </div>
            ))}
          </div>
        ) : null}
        {activeTab === "events" ? (
          <div className="event-list">
            {detail.events.slice(-100).map((event, index) => (
              <div className="event-row" key={`${event.type}-${index}`}>
                <strong>{event.type}</strong>
                <div className="muted">
                  {event.timestamp}
                  {event.node_id ? ` · ${event.node_id}` : ""}
                </div>
                <pre>{JSON.stringify(event.data ?? {}, null, 2)}</pre>
              </div>
            ))}
          </div>
        ) : null}
        {activeTab === "stdout" || activeTab === "stderr" ? <pre>{logQuery.data ?? "No data."}</pre> : null}
        {activeTab === "artifacts" ? (
          <div className="artifact-list">
            {selectedNode?.artifacts.length ? (
              selectedNode.artifacts.map((artifact) => (
                <div className="artifact-row" key={artifact.name}>
                  <a href={`/api/runs/${runId}/nodes/${selectedNode.id}/artifacts/${artifact.name}`} rel="noreferrer" target="_blank">
                    {artifact.name}
                  </a>
                  <span className="muted">{artifact.size} bytes</span>
                </div>
              ))
            ) : (
              <div className="muted">No artifacts.</div>
            )}
          </div>
        ) : null}
      </section>
    </div>
  );
}
