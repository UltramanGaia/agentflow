import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import ReactFlow, { Background, Controls, MarkerType, Position, type Edge, type Node, type NodeTypes } from "reactflow";
import { useNavigate, useParams } from "react-router-dom";
import { useToasts } from "../../app/providers";
import { SegmentedControl } from "../../components/controls/SegmentedControl";
import { AgentNode } from "../../components/graph/AgentNode";
import { InlineNotice } from "../../components/feedback/InlineNotice";
import { ErrorState, LoadingState } from "../../components/feedback/States";
import { PageHeader } from "../../components/layout/PageHeader";
import { PageSection } from "../../components/layout/PageSection";
import { SplitPane } from "../../components/layout/SplitPane";
import { StatusBadge } from "../../components/status/StatusBadge";
import { StatusSummary } from "../../components/status/StatusSummary";
import { cancelRun, getRunDetail, rerunNode, rerunRun, resumeRun } from "../../features/runs/api";
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
type DiagnosticTab = "logs" | "events" | "artifacts" | "overview";

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
      edgeMap.set(`${sourceGroup}->${targetGroup}`, {
        id: `${sourceGroup}->${targetGroup}`,
        source: sourceGroup,
        target: targetGroup,
      });
    });
  });

  return {
    nodes: groupOrder.map((groupId) => {
      const members = groupMembers.get(groupId) ?? [];
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
        agent: Array.from(new Set(members.map((node) => node.agent))).join(", "),
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
    }),
    edges: Array.from(edgeMap.values()),
  };
}

function chooseDefaultNodeId(nodes: RunNode[]) {
  return nodes.find((node) => node.status === "failed")?.id ??
    nodes.find((node) => node.status === "running")?.id ??
    nodes[0]?.id ??
    null;
}

function formatDate(value?: string | null) {
  if (!value) {
    return "n/a";
  }
  return new Date(value).toLocaleString();
}

export function RunDetailPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { runId } = useParams();
  const { pushToast } = useToasts();
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [viewMode, setViewMode] = useState<ViewMode>("stage");
  const [activeTab, setActiveTab] = useState<DiagnosticTab>("logs");
  const [eventFilter, setEventFilter] = useState("all");
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
    onSuccess: async (payload, action) => {
      const nextRunId = payload.redirected_run_id ?? payload.run.id;
      await queryClient.invalidateQueries({ queryKey: ["runs"] });
      await queryClient.invalidateQueries({ queryKey: ["run-detail", runId] });
      pushToast({
        tone: "success",
        title: `Run ${action} accepted`,
        description: nextRunId === runId ? "The current run view was refreshed." : `Opened replacement run ${nextRunId}.`,
      });
      if (nextRunId && nextRunId !== runId) {
        navigate(`/runs/${nextRunId}`);
      }
    },
    onError: (error: Error) => {
      pushToast({ tone: "danger", title: "Run action failed", description: error.message });
    },
  });

  const rerunNodeMutation = useMutation({
    mutationFn: async (nodeId: string) => rerunNode(runId!, nodeId),
    onSuccess: async (payload, nodeId) => {
      const nextRunId = payload.redirected_run_id ?? payload.run.id;
      await queryClient.invalidateQueries({ queryKey: ["runs"] });
      pushToast({
        tone: "success",
        title: "Node rerun queued",
        description: `${nodeId} moved into run ${nextRunId}.`,
      });
      if (nextRunId) {
        navigate(`/runs/${nextRunId}`);
      }
    },
    onError: (error: Error) => {
      pushToast({ tone: "danger", title: "Node rerun failed", description: error.message });
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

  useEffect(() => {
    const nodes = runQuery.data?.graph.nodes;
    if (!nodes?.length || selectedNodeId) {
      return;
    }
    setSelectedNodeId(chooseDefaultNodeId(nodes));
  }, [runQuery.data, selectedNodeId]);

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
  const preferredLogArtifact = selectedSingleNode?.artifacts.find(
    (artifact) => artifact.name === "stderr.log" || artifact.name === "stdout.log",
  );
  const logQuery = useQuery({
    queryKey: ["run-log", runId, selectedSingleNode?.id, preferredLogArtifact?.name],
    queryFn: () => requestText(`/api/runs/${runId}/nodes/${selectedSingleNode?.id}/artifacts/${preferredLogArtifact?.name}`),
    enabled: Boolean(runId && selectedSingleNode?.id && preferredLogArtifact?.name),
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
  const activeNodes = buildRunLayout(activeGraph.nodes).map((node) => ({
    ...node,
    selected: node.id === selectedGraphNode?.id,
  }));
  const edges = activeGraph.edges.map<Edge>((edge) => ({
    ...edge,
    type: "smoothstep",
    markerEnd: { type: MarkerType.ArrowClosed, width: 20, height: 20 },
  }));

  const failedCount = detail.graph.nodes.filter((node) => node.status === "failed").length;
  const runningCount = detail.graph.nodes.filter((node) => node.status === "running").length;
  const completedCount = detail.graph.nodes.filter((node) => node.status === "completed").length;
  const retries = detail.graph.nodes.reduce((sum, node) => sum + Math.max(node.attempts.length - 1, 0), 0);
  const fanoutGroups = new Set(detail.graph.nodes.map((node) => node.fanout_group).filter(Boolean)).size;
  const availableEventTypes = Array.from(new Set(detail.events.map((event) => event.type)));
  const filteredEvents = detail.events.filter((event) => {
    if (eventFilter !== "all" && event.type !== eventFilter) {
      return false;
    }
    if (!selectedGraphNode) {
      return true;
    }
    if (!event.node_id) {
      return true;
    }
    return selectedGraphNode.memberNodeIds.includes(event.node_id);
  });
  const canCancel = detail.run.status === "running";
  const canResume = detail.run.status === "failed" || detail.run.status === "cancelled";

  return (
    <div className="page-stack">
      <PageHeader
        eyebrow="Operations"
        title={detail.run.pipeline.name}
        description="Failure-first runtime inspection with stage and instance drill-down, diagnostic output, and context-aware run actions."
        meta={<StatusBadge status={detail.run.status} />}
        actions={
          <>
            <button className="button danger" disabled={!canCancel} onClick={() => actionMutation.mutate("cancel")} type="button">
              Cancel
            </button>
            <button className="button" disabled={!canResume} onClick={() => actionMutation.mutate("resume")} type="button">
              Resume
            </button>
            <button className="button primary" onClick={() => actionMutation.mutate("rerun")} type="button">
              Rerun
            </button>
          </>
        }
      />

      <div className="metrics-grid">
        <StatusSummary hint={detail.run.id} label="Run id" value={detail.run.id} />
        <StatusSummary hint={`${detail.graph.nodes.length} total nodes`} label="Completed" status="completed" value={completedCount} />
        <StatusSummary hint="Selected by default on failure" label="Failed" status="failed" value={failedCount} />
        <StatusSummary hint={`${fanoutGroups} fanout groups · ${retries} retries`} label="Running" status="running" value={runningCount} />
      </div>

      <SplitPane
        aside={
          <div className="inspector-sections">
            <PageSection title="Node inspector" description="Selection state, attempts, and scoped actions.">
              {selectedGraphNode ? (
                <div className="inspector-card active">
                  <div className="list-row-head">
                    <div>
                      <div className="inspector-title">{selectedGraphNode.title}</div>
                      <div className="muted">{selectedGraphNode.agent}</div>
                    </div>
                    <StatusBadge status={selectedGraphNode.status} />
                  </div>
                  <div className="run-card-meta">
                    <span>{selectedGraphNode.memberNodeIds.length} runtime instance(s)</span>
                    {selectedGraphNode.subtitle ? <span>{selectedGraphNode.subtitle}</span> : null}
                    {selectedGraphNode.meta ? <span>{selectedGraphNode.meta}</span> : null}
                  </div>
                  {selectedSingleNode ? (
                    <button className="button" onClick={() => rerunNodeMutation.mutate(selectedSingleNode.id)} type="button">
                      Rerun node
                    </button>
                  ) : (
                    <InlineNotice tone="warning">Switch to instance view to rerun a specific fanout member.</InlineNotice>
                  )}
                </div>
              ) : (
                <EmptySelection />
              )}
            </PageSection>

            <PageSection title="Selected instances" description="Attempts, timing, and artifact readiness for the current selection.">
              {selectedRunNodes.length ? (
                <div className="list">
                  {selectedRunNodes.map((node) => (
                    <div className="list-item" key={node.id}>
                      <div className="list-row-head">
                        <div>
                          <div className="list-title">{node.id}</div>
                          <div className="muted">{node.agent}</div>
                        </div>
                        <StatusBadge status={node.status} />
                      </div>
                      <div className="run-card-meta">
                        <span>Started {formatDate(node.started_at)}</span>
                        <span>Finished {formatDate(node.finished_at)}</span>
                      </div>
                      {node.attempts.length ? (
                        <pre className="code-block">
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
              ) : (
                <EmptySelection />
              )}
            </PageSection>
          </div>
        }
      >
        <div className="detail-stack">
          <PageSection
            title="Runtime map"
            description="Stage summary for fanout understanding, with instance drill-down when you need the exact shard."
            actions={
              <SegmentedControl
                options={[
                  { label: "Stage view", value: "stage" },
                  { label: "Instance view", value: "instance" },
                ]}
                value={viewMode}
                onChange={setViewMode}
              />
            }
          >
            <div className="flow-panel">
              <ReactFlow
                fitView
                edges={edges}
                nodes={activeNodes}
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
          </PageSection>

          <PageSection
            title="Diagnostics"
            description="Logs first, then event stream and artifacts for the selected node scope."
            actions={
              <SegmentedControl
                options={[
                  { label: "Logs", value: "logs" },
                  { label: "Events", value: "events" },
                  { label: "Artifacts", value: "artifacts" },
                  { label: "Overview", value: "overview" },
                ]}
                value={activeTab}
                onChange={setActiveTab}
              />
            }
          >
            {activeTab === "logs" ? (
              selectedSingleNode ? (
                preferredLogArtifact ? (
                  <pre className="log-viewer">{logQuery.data ?? "Loading log..."}</pre>
                ) : (
                  <InlineNotice tone="warning">The selected node has no stdout/stderr artifact yet.</InlineNotice>
                )
              ) : (
                <InlineNotice tone="warning">Select a single runtime instance to inspect stdout or stderr directly.</InlineNotice>
              )
            ) : null}

            {activeTab === "events" ? (
              <div className="diagnostic-stack">
                <label className="field">
                  <span className="field-label">Event filter</span>
                  <select value={eventFilter} onChange={(event) => setEventFilter(event.target.value)}>
                    <option value="all">All events</option>
                    {availableEventTypes.map((type) => (
                      <option key={type} value={type}>
                        {type}
                      </option>
                    ))}
                  </select>
                </label>
                <div className="event-list">
                  {filteredEvents.length ? (
                    filteredEvents.slice(-80).map((event, index) => (
                      <div className="event-row" key={`${event.type}-${index}`}>
                        <div className="list-row-head">
                          <strong>{event.type}</strong>
                          <span className="muted">{formatDate(event.timestamp)}</span>
                        </div>
                        <div className="run-card-meta">
                          <span>{event.node_id ?? "run-wide event"}</span>
                        </div>
                        <pre>{JSON.stringify(event.data ?? {}, null, 2)}</pre>
                      </div>
                    ))
                  ) : (
                    <div className="event-row">No events match this selection.</div>
                  )}
                </div>
              </div>
            ) : null}

            {activeTab === "artifacts" ? (
              selectedRunNodes.length ? (
                <div className="artifact-list">
                  {selectedRunNodes.flatMap((node) =>
                    node.artifacts.map((artifact) => (
                      <div className="artifact-row" key={`${node.id}-${artifact.name}`}>
                        <div>
                          <strong>{artifact.name}</strong>
                          <div className="muted">{node.id}</div>
                        </div>
                        <a
                          className="button"
                          href={`/api/runs/${runId}/nodes/${node.id}/artifacts/${artifact.name}`}
                          rel="noreferrer"
                          target="_blank"
                        >
                          Open
                        </a>
                      </div>
                    )),
                  )}
                </div>
              ) : (
                <EmptySelection />
              )
            ) : null}

            {activeTab === "overview" ? (
              <div className="list">
                {activeGraph.nodes.map((node) => (
                  <button
                    className={`list-item${node.id === selectedGraphNode?.id ? " active" : ""}`}
                    key={node.id}
                    onClick={() => setSelectedNodeId(node.id)}
                    type="button"
                  >
                    <div className="list-row-head">
                      <div>
                        <div className="list-title">{node.title}</div>
                        <div className="muted">{node.agent}</div>
                      </div>
                      <StatusBadge status={node.status} />
                    </div>
                    <div className="run-card-meta">
                      <span>{node.memberNodeIds.length} instance(s)</span>
                      {node.meta ? <span>{node.meta}</span> : null}
                    </div>
                  </button>
                ))}
              </div>
            ) : null}
          </PageSection>
        </div>
      </SplitPane>
    </div>
  );
}

function EmptySelection() {
  return <InlineNotice tone="info">Select a node from the runtime map to inspect logs, attempts, and artifacts.</InlineNotice>;
}
