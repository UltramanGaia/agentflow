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
import { cancelRun, rerunNode, rerunRun, resumeRun } from "../../features/runs/api";
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

  const rerunNodeMutation = useMutation({
    mutationFn: async (nodeId: string) => rerunNode(runId, nodeId),
    onSuccess: async (payload, nodeId) => {
      const nextRunId = payload.redirected_run_id ?? payload.run.id;
      await queryClient.invalidateQueries({ queryKey: ["runs"] });
      pushToast({
        tone: "success",
        title: "Node rerun queued",
        description: `${nodeId} moved into run ${nextRunId}.`,
      });
      if (nextRunId) {
        onNavigateRun?.(nextRunId);
      }
    },
    onError: (error: Error) => {
      pushToast({ tone: "danger", title: "Node rerun failed", description: error.message });
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

  const selectedRunNodes = useMemo(() => {
    if (!selectedGraphNode) {
      return [];
    }
    const nodeById = new Map(detail.graph.nodes.map((node) => [node.id, node]));
    return selectedGraphNode.memberNodeIds.map((nodeId) => nodeById.get(nodeId)).filter((node): node is RunNode => Boolean(node));
  }, [detail, selectedGraphNode]);

  const selectedSingleNode = selectedRunNodes.length === 1 ? selectedRunNodes[0] : null;
  const preferredLogArtifact = selectedSingleNode?.artifacts.find(
    (artifact) => artifact.name === "stderr.log" || artifact.name === "stdout.log",
  );
  const logQuery = useQuery({
    queryKey: ["run-log", runId, selectedSingleNode?.id, preferredLogArtifact?.name],
    queryFn: () => requestText(`/api/runs/${runId}/nodes/${selectedSingleNode?.id}/artifacts/${preferredLogArtifact?.name}`),
    enabled: Boolean(runId && selectedSingleNode?.id && preferredLogArtifact?.name),
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
          description="Focused node inspection from the runtime map."
          onClose={() => setIsNodeDialogOpen(false)}
          title={dialogTitle}
        >
          {activeTab === "logs" ? (
            selectedSingleNode ? (
              preferredLogArtifact ? (
                logQuery.isLoading ? (
                  <div className="event-row">Loading {preferredLogArtifact.name}...</div>
                ) : logQuery.error ? (
                  <InlineNotice tone="danger">{logQuery.error.message}</InlineNotice>
                ) : (
                  <pre className="log-viewer">{logQuery.data ?? "No log output available yet."}</pre>
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
            <div className="diagnostic-stack">
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
                  <button
                    className="button"
                    disabled={rerunNodeMutation.isPending}
                    onClick={() => rerunNodeMutation.mutate(selectedSingleNode.id)}
                    type="button"
                  >
                    {rerunNodeMutation.isPending ? "Queueing node rerun..." : "Rerun node"}
                  </button>
                ) : null}
              </div>
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
                  </div>
                ))}
              </div>
            </div>
          ) : null}
        </ModalDialog>
      ) : null}
    </div>
  );
}

function EmptySelection() {
  return <div className="event-row">Select a node with available runtime instances to inspect artifacts.</div>;
}
