import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import ReactFlow, { Background, Controls, MarkerType, type Edge, type NodeTypes } from "reactflow";
import { useToasts } from "../../app/providers";
import { SegmentedControl } from "../../components/controls/SegmentedControl";
import { AgentNode } from "../../components/graph/AgentNode";
import { InlineNotice } from "../../components/feedback/InlineNotice";
import { ModalDialog } from "../../components/feedback/ModalDialog";
import { PageHeader } from "../../components/layout/PageHeader";
import { PageSection } from "../../components/layout/PageSection";
import { StatusBadge } from "../../components/status/StatusBadge";
import { cancelRun, rerunRun, resumeRun } from "../../features/runs/api";
import {
  buildInstanceGraph,
  buildRunLayout,
  buildStageGraph,
  chooseDefaultGraphNodeId,
  chooseDefaultNodeId,
} from "../../features/run-viewer/runtimeGraph";
import { requestText } from "../../lib/http";
import type { RunDetail, RunNode } from "../../types/api";

const nodeTypes: NodeTypes = { agentNode: AgentNode };

type ViewMode = "stage" | "instance";
type DiagnosticTab = "logs" | "events" | "artifacts" | "overview";

function formatDate(value?: string | null) {
  if (!value) {
    return "n/a";
  }
  return new Date(value).toLocaleString();
}

function formatStatusLabel(value?: string | null) {
  if (!value) {
    return "n/a";
  }
  return value.replace(/_/g, " ");
}

function formatBytes(value: number) {
  if (value < 1024) {
    return `${value} B`;
  }
  const units = ["KB", "MB", "GB", "TB"];
  let size = value / 1024;
  let unitIndex = 0;
  while (size >= 1024 && unitIndex < units.length - 1) {
    size /= 1024;
    unitIndex += 1;
  }
  return `${size.toFixed(size >= 10 ? 0 : 1)} ${units[unitIndex]}`;
}

function classifyArtifact(name: string) {
  if (name.endsWith(".log")) {
    return "log";
  }
  if (name.endsWith(".json") || name.endsWith(".yaml") || name.endsWith(".yml")) {
    return "structured";
  }
  return "file";
}

function isPreviewableArtifact(name: string) {
  const lowered = name.toLowerCase();
  return [".log", ".txt", ".json", ".yaml", ".yml", ".md", ".csv", ".xml"].some((suffix) => lowered.endsWith(suffix));
}

interface ArtifactSelection {
  key: string;
  nodeId: string;
  nodeStatus: string;
  nodeAgent: string;
  name: string;
  size: number;
}

interface RunDetailWorkspaceProps {
  detail: RunDetail;
  runId: string;
  onNavigateRun?: (runId: string) => void;
  embedded?: boolean;
}

export function RunDetailWorkspace({ detail, runId, onNavigateRun, embedded = false }: RunDetailWorkspaceProps) {
  const queryClient = useQueryClient();
  const { pushToast } = useToasts();
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [viewMode, setViewMode] = useState<ViewMode>("stage");
  const [activeTab, setActiveTab] = useState<DiagnosticTab>("logs");
  const [eventFilter, setEventFilter] = useState("all");
  const [isNodeDialogOpen, setIsNodeDialogOpen] = useState(false);
  const [selectedArtifactKey, setSelectedArtifactKey] = useState<string | null>(null);

  const actionMutation = useMutation({
    mutationFn: async (action: "cancel" | "resume" | "rerun") => {
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
        onNavigateRun?.(nextRunId);
      }
    },
    onError: (error: Error) => {
      pushToast({ tone: "danger", title: "Run action failed", description: error.message });
    },
  });

  const runtimeGraphs = useMemo(() => {
    return {
      instance: buildInstanceGraph(detail.graph.nodes),
      stage: buildStageGraph(detail.graph.nodes),
    };
  }, [detail]);

  const activeGraph = runtimeGraphs[viewMode];

  useEffect(() => {
    if (!detail.graph.nodes.length || selectedNodeId) {
      return;
    }
    setSelectedNodeId(chooseDefaultNodeId(detail.graph.nodes));
  }, [detail, selectedNodeId]);

  useEffect(() => {
    if (!activeGraph.nodes.length) {
      return;
    }
    if (selectedNodeId && activeGraph.nodes.some((node) => node.id === selectedNodeId)) {
      return;
    }
    setSelectedNodeId(chooseDefaultGraphNodeId(activeGraph.nodes));
  }, [activeGraph, selectedNodeId]);

  const selectedGraphNode = useMemo(() => {
    return activeGraph.nodes.find((node) => node.id === selectedNodeId) ?? activeGraph.nodes[0] ?? null;
  }, [activeGraph, selectedNodeId]);

  useEffect(() => {
    setSelectedArtifactKey(null);
  }, [activeTab, selectedGraphNode?.id]);

  const selectedRunNodes = useMemo(() => {
    if (!selectedGraphNode) {
      return [];
    }
    const nodeById = new Map(detail.graph.nodes.map((node) => [node.id, node]));
    return selectedGraphNode.memberNodeIds.map((nodeId) => nodeById.get(nodeId)).filter((node): node is RunNode => Boolean(node));
  }, [detail, selectedGraphNode]);

  const selectedSingleNode = selectedRunNodes.length === 1 ? selectedRunNodes[0] : null;
  const artifactItems: ArtifactSelection[] = selectedRunNodes.flatMap((node) =>
    node.artifacts.map((artifact) => ({
      key: `${node.id}:${artifact.name}`,
      nodeId: node.id,
      nodeStatus: node.status,
      nodeAgent: node.agent,
      name: artifact.name,
      size: artifact.size,
    })),
  );
  const selectedArtifact = artifactItems.find((artifact) => artifact.key === selectedArtifactKey) ?? artifactItems[0] ?? null;
  const totalArtifacts = selectedRunNodes.reduce((count, node) => count + node.artifacts.length, 0);
  const preferredLogArtifact = selectedSingleNode?.artifacts.find(
    (artifact) => artifact.name === "stderr.log" || artifact.name === "stdout.log",
  );
  const logQuery = useQuery({
    queryKey: ["run-log", runId, selectedSingleNode?.id, preferredLogArtifact?.name],
    queryFn: () => requestText(`/api/runs/${runId}/nodes/${selectedSingleNode?.id}/artifacts/${preferredLogArtifact?.name}`),
    enabled: Boolean(runId && selectedSingleNode?.id && preferredLogArtifact?.name),
  });
  const artifactPreviewQuery = useQuery({
    queryKey: ["artifact-preview", runId, selectedArtifact?.nodeId, selectedArtifact?.name],
    queryFn: () => requestText(`/api/runs/${runId}/nodes/${selectedArtifact?.nodeId}/artifacts/${selectedArtifact?.name}`),
    enabled: Boolean(runId && selectedArtifact?.nodeId && selectedArtifact?.name && isPreviewableArtifact(selectedArtifact.name)),
  });

  const activeNodes = buildRunLayout(activeGraph.nodes, {
    onInspect: (nodeId) => {
      setSelectedNodeId(nodeId);
      setIsNodeDialogOpen(true);
    },
  }).map((node) => ({
    ...node,
    selected: node.id === selectedGraphNode?.id,
  }));
  const edges = activeGraph.edges.map<Edge>((edge) => ({
    ...edge,
    type: "smoothstep",
    markerEnd: { type: MarkerType.ArrowClosed, width: 20, height: 20 },
  }));

  const availableEventTypes = Array.from(new Set(detail.events.map((event) => event.type)));
  const filteredEvents = detail.events.filter((event) => {
    if (eventFilter !== "all" && event.type !== eventFilter) {
      return false;
    }
    if (!selectedGraphNode || !event.node_id) {
      return true;
    }
    return selectedGraphNode.memberNodeIds.includes(event.node_id);
  });
  const canCancel = detail.run.status === "running";
  const canResume = detail.run.status === "failed" || detail.run.status === "cancelled";
  const activeAction = actionMutation.variables;
  const dialogTitle = selectedGraphNode ? `${selectedGraphNode.title} diagnostics` : "Node diagnostics";
  const dialogDescription = selectedSingleNode
    ? `Focused inspection for ${selectedSingleNode.id}.`
    : `Focused inspection for ${selectedGraphNode?.memberNodeIds.length ?? 0} runtime instances.`;

  return (
    <div className="page-stack">
      {!embedded ? (
        <PageHeader
          eyebrow="Operations"
          title={detail.run.pipeline.name}
          description="Failure-first runtime inspection with stage and instance drill-down, diagnostic output, and context-aware run actions."
          meta={<StatusBadge status={detail.run.status} />}
          actions={
            <>
              <button
                className="button danger"
                disabled={!canCancel || actionMutation.isPending}
                onClick={() => actionMutation.mutate("cancel")}
                type="button"
              >
                {activeAction === "cancel" && actionMutation.isPending ? "Cancelling..." : "Cancel"}
              </button>
              <button
                className="button"
                disabled={!canResume || actionMutation.isPending}
                onClick={() => actionMutation.mutate("resume")}
                type="button"
              >
                {activeAction === "resume" && actionMutation.isPending ? "Resuming..." : "Resume"}
              </button>
              <button
                className="button primary"
                disabled={actionMutation.isPending}
                onClick={() => actionMutation.mutate("rerun")}
                type="button"
              >
                {activeAction === "rerun" && actionMutation.isPending ? "Queueing rerun..." : "Rerun"}
              </button>
            </>
          }
        />
      ) : null}

      {embedded ? (
        <div className="section-header">
          <div>
            <div className="page-title-row">
              <h2>{detail.run.pipeline.name}</h2>
              <StatusBadge status={detail.run.status} />
            </div>
          </div>
          <div className="page-actions">
            <button
              className="button danger"
              disabled={!canCancel || actionMutation.isPending}
              onClick={() => actionMutation.mutate("cancel")}
              type="button"
            >
              {activeAction === "cancel" && actionMutation.isPending ? "Cancelling..." : "Cancel"}
            </button>
            <button
              className="button"
              disabled={!canResume || actionMutation.isPending}
              onClick={() => actionMutation.mutate("resume")}
              type="button"
            >
              {activeAction === "resume" && actionMutation.isPending ? "Resuming..." : "Resume"}
            </button>
            <button
              className="button primary"
              disabled={actionMutation.isPending}
              onClick={() => actionMutation.mutate("rerun")}
              type="button"
            >
              {activeAction === "rerun" && actionMutation.isPending ? "Queueing rerun..." : "Rerun"}
            </button>
          </div>
        </div>
      ) : null}

      <div className="detail-stack">
        <PageSection
          title={embedded ? undefined : "Runtime map"}
          description={
            embedded ? undefined : "The runtime map is the primary workspace. Use the node card's details button to open logs, events, artifacts, and attempts."
          }
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
      </div>

      {isNodeDialogOpen && selectedGraphNode ? (
        <ModalDialog
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
          description={dialogDescription}
          onClose={() => setIsNodeDialogOpen(false)}
          title={dialogTitle}
        >
          <div className="diagnostic-layout">
            <div className="diagnostic-main">
              {activeTab === "logs" ? (
                selectedSingleNode ? (
                  preferredLogArtifact ? (
                    logQuery.isLoading ? (
                      <div className="event-row">Loading {preferredLogArtifact.name}...</div>
                    ) : logQuery.error ? (
                      <InlineNotice tone="danger">{logQuery.error.message}</InlineNotice>
                    ) : (
                      <div className="diagnostic-stack">
                        <div className="inline-meta panel">
                          <span>{preferredLogArtifact.name}</span>
                          <span>{selectedSingleNode.id}</span>
                        </div>
                        <pre className="log-viewer">{logQuery.data ?? "No log output available yet."}</pre>
                      </div>
                    )
                  ) : (
                    <InlineNotice tone="warning">The selected node has no stdout/stderr artifact yet.</InlineNotice>
                  )
                ) : (
                  <InlineNotice tone="warning">Select a single runtime instance to inspect stdout or stderr directly.</InlineNotice>
                )
              ) : null}

              {activeTab === "events" ? (
                <div className="diagnostic-stack">
                  <div className="inline-meta panel">
                    <span>{filteredEvents.length} matching event(s)</span>
                    <label className="field diagnostic-inline-filter">
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
                  </div>
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
                  <div className="diagnostic-stack">
                    <div className="inline-meta panel">
                      <span>{totalArtifacts} artifact(s)</span>
                      <span>
                        {selectedArtifact ? `Previewing ${selectedArtifact.name}` : `Across ${selectedRunNodes.length} instance(s)`}
                      </span>
                    </div>
                    <div className="artifact-browser">
                      <div className="artifact-groups">
                        {selectedRunNodes.map((node) => (
                          <section className="artifact-group panel" key={node.id}>
                            <div className="list-row-head">
                              <div>
                                <div className="list-title">{node.id}</div>
                                <div className="muted">{node.agent}</div>
                              </div>
                              <StatusBadge status={node.status} />
                            </div>
                            <div className="run-card-meta">
                              <span>{node.artifacts.length} artifact(s)</span>
                              <span>Finished {formatDate(node.finished_at)}</span>
                            </div>
                            {node.artifacts.length ? (
                              <div className="artifact-grid">
                                {node.artifacts.map((artifact) => {
                                  const artifactKind = classifyArtifact(artifact.name);
                                  const artifactKey = `${node.id}:${artifact.name}`;
                                  const isActive = selectedArtifact?.key === artifactKey;
                                  return (
                                    <button
                                      className={`artifact-card${isActive ? " active" : ""}`}
                                      key={artifactKey}
                                      onClick={() => setSelectedArtifactKey(artifactKey)}
                                      type="button"
                                    >
                                      <div className="artifact-card-top">
                                        <span className={`artifact-kind artifact-kind-${artifactKind}`}>{artifactKind}</span>
                                        <span className="muted">{formatBytes(artifact.size)}</span>
                                      </div>
                                      <div className="artifact-name">{artifact.name}</div>
                                      <div className="artifact-card-footer">
                                        <span className="muted">{node.id}</span>
                                        <span className="artifact-card-action">Preview</span>
                                      </div>
                                    </button>
                                  );
                                })}
                              </div>
                            ) : (
                              <div className="event-row">No artifacts produced for this instance.</div>
                            )}
                          </section>
                        ))}
                      </div>
                      <div className="artifact-preview panel">
                        {selectedArtifact ? (
                          <div className="diagnostic-stack">
                            <div className="list-row-head">
                              <div>
                                <div className="artifact-name">{selectedArtifact.name}</div>
                                <div className="run-card-meta">
                                  <span>{selectedArtifact.nodeId}</span>
                                  <span>{selectedArtifact.nodeAgent}</span>
                                  <span>{formatBytes(selectedArtifact.size)}</span>
                                </div>
                              </div>
                              <StatusBadge status={selectedArtifact.nodeStatus} />
                            </div>
                            {isPreviewableArtifact(selectedArtifact.name) ? (
                              artifactPreviewQuery.isLoading ? (
                                <div className="event-row">Loading preview...</div>
                              ) : artifactPreviewQuery.error ? (
                                <InlineNotice tone="danger">{artifactPreviewQuery.error.message}</InlineNotice>
                              ) : (
                                <pre className="log-viewer artifact-preview-content">
                                  {artifactPreviewQuery.data ?? "No preview content available."}
                                </pre>
                              )
                            ) : (
                              <InlineNotice tone="info">
                                This artifact is not previewable inline yet. Use download if you need the raw file.
                              </InlineNotice>
                            )}
                            <div className="artifact-preview-actions">
                              <a
                                className="button"
                                download={selectedArtifact.name}
                                href={`/api/runs/${runId}/nodes/${selectedArtifact.nodeId}/artifacts/${selectedArtifact.name}`}
                              >
                                Download
                              </a>
                            </div>
                          </div>
                        ) : (
                          <div className="event-row">Select an artifact to inspect it here.</div>
                        )}
                      </div>
                    </div>
                  </div>
                ) : (
                  <EmptySelection />
                )
              ) : null}

              {activeTab === "overview" ? (
                <div className="diagnostic-shell">
                  <div className="inspector-grid">
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
                          <span>Attempts {node.attempts.length}</span>
                          <span>Artifacts {node.artifacts.length}</span>
                        </div>
                        {node.attempts.length ? (
                          <div className="diagnostic-attempt-list">
                            {node.attempts.map((attempt) => (
                              <div className="diagnostic-attempt-row" key={`${node.id}-${attempt.number}`}>
                                <span>Attempt #{attempt.number}</span>
                                <span>{formatStatusLabel(attempt.status)}</span>
                                <span>Exit {attempt.exit_code ?? "n/a"}</span>
                              </div>
                            ))}
                          </div>
                        ) : null}
                      </div>
                    ))}
                  </div>
                </div>
              ) : null}
            </div>
          </div>
        </ModalDialog>
      ) : null}
    </div>
  );
}

function EmptySelection() {
  return <div className="event-row">Select a node with available runtime instances to inspect artifacts.</div>;
}
