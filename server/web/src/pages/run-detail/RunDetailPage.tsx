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
const NODE_HEIGHT = 152;
const COLUMN_GAP = 120;
const ROW_GAP = 44;
const PADDING_X = 80;
const PADDING_Y = 80;

type ViewMode = "stage" | "instance";

interface RuntimeGraphNode {
  id: string;
  title: string;
  agent: string;
  status: string;
  depends_on: string[];
  memberNodeIds: string[];
  subtitle?: string;
  meta?: string;
}

interface RuntimeGraphEdge {
  id: string;
  source: string;
  target: string;
}

interface RuntimeGraphModel {
  nodes: RuntimeGraphNode[];
  edges: RuntimeGraphEdge[];
}

function buildRunLayout(graphNodes: RuntimeGraphNode[]): Node[] {
  const nodeById = new Map(graphNodes.map((node) => [node.id, node]));
  const layerById = new Map<string, number>();
  const indegree = new Map<string, number>();
  const downstream = new Map<string, string[]>();
  const order = new Map(graphNodes.map((node, index) => [node.id, index]));

  graphNodes.forEach((node) => {
    indegree.set(node.id, 0);
    downstream.set(node.id, []);
  });

  graphNodes.forEach((node) => {
    node.depends_on.forEach((dependency) => {
      if (!nodeById.has(dependency)) {
        return;
      }
      indegree.set(node.id, (indegree.get(node.id) ?? 0) + 1);
      downstream.get(dependency)?.push(node.id);
    });
  });

  const queue = graphNodes
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

  const remainingIds = graphNodes
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

  return graphNodes.map<Node>((node) => {
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
        title: node.title,
        agent: node.agent,
        status: node.status,
        subtitle: node.subtitle,
        meta: node.meta,
      },
      selected: false,
    };
  });
}

function aggregateStatus(statuses: string[]): string {
  const rank: Record<string, number> = {
    failed: 0,
    cancelled: 1,
    cancelling: 2,
    running: 3,
    pending: 4,
    queued: 5,
    ready: 6,
    completed: 7,
  };
  return [...statuses].sort((left, right) => (rank[left] ?? 999) - (rank[right] ?? 999))[0] ?? "pending";
}

function buildInstanceGraph(runNodes: RunNode[]): RuntimeGraphModel {
  return {
    nodes: runNodes.map((node) => {
      const metaParts: string[] = [];
      if (node.attempts.length > 1) {
        metaParts.push(`${node.attempts.length} attempts`);
      }
      if (node.tick_count > 0) {
        metaParts.push(`${node.tick_count} ticks`);
      }
      return {
        id: node.id,
        title: node.id,
        agent: node.agent,
        status: node.status,
        depends_on: node.depends_on,
        memberNodeIds: [node.id],
        subtitle: node.fanout_group ? `fanout · ${node.fanout_group}` : undefined,
        meta: metaParts.length ? metaParts.join(" · ") : undefined,
      };
    }),
    edges: runNodes.flatMap((node) =>
      node.depends_on.map((dependency) => ({
        id: `${dependency}->${node.id}`,
        source: dependency,
        target: node.id,
      })),
    ),
  };
}

function buildStageGraph(runNodes: RunNode[]): RuntimeGraphModel {
  const nodeToGroup = new Map<string, string>();
  const groupMembers = new Map<string, RunNode[]>();

  runNodes.forEach((node) => {
    const groupId = node.fanout_group ?? node.id;
    nodeToGroup.set(node.id, groupId);
    const members = groupMembers.get(groupId) ?? [];
    members.push(node);
    groupMembers.set(groupId, members);
  });

  const groupOrder = Array.from(groupMembers.keys()).sort((left, right) => {
    const leftIndex = runNodes.findIndex((node) => (node.fanout_group ?? node.id) === left);
    const rightIndex = runNodes.findIndex((node) => (node.fanout_group ?? node.id) === right);
    return leftIndex - rightIndex;
  });

  const edgeMap = new Map<string, RuntimeGraphEdge>();
  runNodes.forEach((node) => {
    const targetGroup = nodeToGroup.get(node.id) ?? node.id;
    node.depends_on.forEach((dependency) => {
      const sourceGroup = nodeToGroup.get(dependency) ?? dependency;
      if (sourceGroup === targetGroup) {
        return;
      }
      const edgeId = `${sourceGroup}->${targetGroup}`;
      edgeMap.set(edgeId, { id: edgeId, source: sourceGroup, target: targetGroup });
    });
  });

  const nodes = groupOrder.map<RuntimeGraphNode>((groupId) => {
    const members = groupMembers.get(groupId) ?? [];
    const agentNames = Array.from(new Set(members.map((node) => node.agent)));
    const totalAttempts = members.reduce((sum, node) => sum + Math.max(node.attempts.length, 1), 0);
    const totalTicks = members.reduce((sum, node) => sum + node.tick_count, 0);
    const metaParts: string[] = [];
    if (totalAttempts > members.length) {
      metaParts.push(`${totalAttempts} attempts`);
    }
    if (totalTicks > 0) {
      metaParts.push(`${totalTicks} ticks`);
    }
    return {
      id: groupId,
      title: groupId,
      agent: agentNames.length === 1 ? agentNames[0] : `${agentNames.length} agents`,
      status: aggregateStatus(members.map((node) => node.status)),
      depends_on: Array.from(
        new Set(
          members.flatMap((node) =>
            node.depends_on
              .map((dependency) => nodeToGroup.get(dependency) ?? dependency)
              .filter((dependency) => dependency !== groupId),
          ),
        ),
      ),
      memberNodeIds: members.map((node) => node.id),
      subtitle: members.length > 1 ? `${members.length} instances` : "1 instance",
      meta: metaParts.length ? metaParts.join(" · ") : undefined,
    };
  });

  return {
    nodes,
    edges: Array.from(edgeMap.values()),
  };
}

export function RunDetailPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { runId } = useParams();
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [viewMode, setViewMode] = useState<ViewMode>("stage");
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

  const runtimeGraphs = useMemo(() => {
    const detail = runQuery.data;
    if (!detail) {
      return null;
    }
    return {
      instance: buildInstanceGraph(detail.graph.nodes),
      stage: buildStageGraph(detail.graph.nodes),
    };
  }, [runQuery.data]);

  const activeGraph = runtimeGraphs?.[viewMode] ?? null;

  const selectedGraphNode = useMemo(() => {
    if (!activeGraph) {
      return null;
    }
    return activeGraph.nodes.find((node) => node.id === selectedNodeId) ?? activeGraph.nodes[0] ?? null;
  }, [activeGraph, selectedNodeId]);

  const selectedRunNodes = useMemo(() => {
    const detail = runQuery.data;
    if (!detail || !selectedGraphNode) {
      return [];
    }
    const nodeById = new Map(detail.graph.nodes.map((node) => [node.id, node]));
    return selectedGraphNode.memberNodeIds.map((nodeId) => nodeById.get(nodeId)).filter((node): node is RunNode => Boolean(node));
  }, [runQuery.data, selectedGraphNode]);

  const selectedSingleNode = selectedRunNodes.length === 1 ? selectedRunNodes[0] : null;

  const logQuery = useQuery({
    queryKey: ["run-log", runId, selectedSingleNode?.id, activeTab],
    queryFn: () =>
      requestText(
        `/api/runs/${runId}/nodes/${selectedSingleNode?.id}/artifacts/${activeTab === "stdout" ? "stdout.log" : "stderr.log"}`,
      ),
    enabled:
      Boolean(runId && selectedSingleNode?.id) &&
      (activeTab === "stdout" || activeTab === "stderr") &&
      Boolean(selectedSingleNode?.artifacts.some((artifact) => artifact.name === `${activeTab}.log`)),
  });

  if (runQuery.isLoading) {
    return <LoadingState>Loading run detail...</LoadingState>;
  }
  if (runQuery.error) {
    return <ErrorState message={runQuery.error.message} />;
  }
  if (!runQuery.data || !activeGraph) {
    return <ErrorState message="Run detail not found." />;
  }

  const detail = runQuery.data;
  const nodes = buildRunLayout(activeGraph.nodes).map((node) => ({
    ...node,
    selected: node.id === selectedGraphNode?.id,
  }));
  const edges = activeGraph.edges.map<Edge>((edge) => ({
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
        <div className="tabs">
          <button className={`tab${viewMode === "stage" ? " active" : ""}`} onClick={() => setViewMode("stage")} type="button">
            Stage View
          </button>
          <button className={`tab${viewMode === "instance" ? " active" : ""}`} onClick={() => setViewMode("instance")} type="button">
            Instance View
          </button>
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
            {activeGraph.nodes.map((node) => {
              const memberCount = node.memberNodeIds.length;
              return (
                <div className="list-item" key={node.id}>
                  <div className="section-head compact">
                    <button className="button" onClick={() => setSelectedNodeId(node.id)} type="button">
                      {node.title}
                    </button>
                    <StatusBadge status={node.status} />
                  </div>
                  <div className="muted">
                    {node.agent}
                    {memberCount > 1 ? ` · ${memberCount} instances` : ""}
                    {node.meta ? ` · ${node.meta}` : ""}
                  </div>
                  <div className="row-wrap">
                    {memberCount === 1 ? (
                      <button className="button" onClick={() => rerunNodeMutation.mutate(node.memberNodeIds[0])} type="button">
                        Rerun Node
                      </button>
                    ) : (
                      <div className="muted">Switch to instance view to rerun a specific shard.</div>
                    )}
                  </div>
                </div>
              );
            })}
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
        {activeTab === "stdout" || activeTab === "stderr" ? (
          selectedSingleNode ? (
            <pre>{logQuery.data ?? "No data."}</pre>
          ) : (
            <div className="muted">Select a single runtime instance in Instance View to inspect {activeTab}.</div>
          )
        ) : null}
        {activeTab === "artifacts" ? (
          selectedRunNodes.length ? (
            selectedSingleNode ? (
              <div className="artifact-list">
                {selectedSingleNode.artifacts.length ? (
                  selectedSingleNode.artifacts.map((artifact) => (
                    <div className="artifact-row" key={artifact.name}>
                      <a
                        href={`/api/runs/${runId}/nodes/${selectedSingleNode.id}/artifacts/${artifact.name}`}
                        rel="noreferrer"
                        target="_blank"
                      >
                        {artifact.name}
                      </a>
                      <span className="muted">{artifact.size} bytes</span>
                    </div>
                  ))
                ) : (
                  <div className="muted">No artifacts.</div>
                )}
              </div>
            ) : (
              <div className="artifact-list">
                {selectedRunNodes.map((node) => (
                  <div className="list-item" key={node.id}>
                    <div className="section-head compact">
                      <strong>{node.id}</strong>
                      <StatusBadge status={node.status} />
                    </div>
                    {node.artifacts.length ? (
                      node.artifacts.map((artifact) => (
                        <div className="artifact-row" key={`${node.id}-${artifact.name}`}>
                          <a href={`/api/runs/${runId}/nodes/${node.id}/artifacts/${artifact.name}`} rel="noreferrer" target="_blank">
                            {artifact.name}
                          </a>
                          <span className="muted">{artifact.size} bytes</span>
                        </div>
                      ))
                    ) : (
                      <div className="muted">No artifacts.</div>
                    )}
                  </div>
                ))}
              </div>
            )
          ) : (
            <div className="muted">No artifacts.</div>
          )
        ) : null}
        {selectedGraphNode ? (
          <div className="list-item">
            <div className="section-head compact">
              <strong>{selectedGraphNode.title}</strong>
              <StatusBadge status={selectedGraphNode.status} />
            </div>
            <div className="muted">
              {selectedGraphNode.agent}
              {selectedGraphNode.memberNodeIds.length > 1 ? ` · ${selectedGraphNode.memberNodeIds.length} runtime instances` : ""}
            </div>
            {selectedRunNodes.map((node) => (
              <div key={node.id}>
                <div className="muted">
                  {node.id}
                  {node.attempts.length > 1 ? ` · ${node.attempts.length} attempts` : ""}
                  {node.tick_count > 0 ? ` · ${node.tick_count} ticks` : ""}
                </div>
                {node.attempts.length ? (
                  <pre>
                    {node.attempts
                      .map((attempt) => {
                        const parts = [`attempt ${attempt.number}`, attempt.status];
                        if (attempt.exit_code !== null && attempt.exit_code !== undefined) {
                          parts.push(`exit ${attempt.exit_code}`);
                        }
                        return parts.join(" · ");
                      })
                      .join("\n")}
                  </pre>
                ) : null}
              </div>
            ))}
          </div>
        ) : null}
      </section>
    </div>
  );
}
