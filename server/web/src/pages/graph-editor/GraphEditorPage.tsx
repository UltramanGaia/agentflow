import Editor from "@monaco-editor/react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import ReactFlow, {
  Background,
  Controls,
  MiniMap,
  ReactFlowProvider,
  useReactFlow,
  type NodeTypes,
} from "reactflow";
import { useBeforeUnload, useNavigate, useParams } from "react-router-dom";
import { useToasts } from "../../app/providers";
import { SegmentedControl } from "../../components/controls/SegmentedControl";
import { AgentNode } from "../../components/graph/AgentNode";
import { InlineNotice } from "../../components/feedback/InlineNotice";
import { ErrorState, LoadingState } from "../../components/feedback/States";
import { PageHeader } from "../../components/layout/PageHeader";
import { PageSection } from "../../components/layout/PageSection";
import { SplitPane } from "../../components/layout/SplitPane";
import { defaultGraph } from "../../features/graph-editor/mappers";
import { useGraphEditorStore } from "../../features/graph-editor/store";
import {
  createGraph,
  exportGraphPython,
  getGraph,
  importGraph,
  updateGraph,
  validateGraph,
} from "../../features/graphs/api";
import { createRun } from "../../features/runs/api";
import type { PipelineNode } from "../../types/api";

const nodeTypes: NodeTypes = { agentNode: AgentNode };

export function GraphEditorPage() {
  return (
    <ReactFlowProvider>
      <GraphEditorPageInner />
    </ReactFlowProvider>
  );
}

function GraphEditorPageInner() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const reactFlow = useReactFlow();
  const { graphId = "new" } = useParams();
  const { pushToast } = useToasts();
  const {
    draft,
    flowNodes,
    flowEdges,
    selectedNodeId,
    dirty,
    exportContent,
    loadGraph,
    setSelectedNodeId,
    setExportContent,
    updateGraphMeta,
    updatePipelineSetting,
    updateSelectedNode,
    setSelectedNodeDependencies,
    applyPipelineJson,
    addNodeWithTemplate,
    removeSelectedNode,
    onNodesChange,
    onEdgesChange,
    onConnect,
    snapshot,
  } = useGraphEditorStore();
  const [editorMode, setEditorMode] = useState<"structured" | "advanced">("structured");
  const [importPath, setImportPath] = useState("");
  const [newNodeId, setNewNodeId] = useState("");
  const [newNodeAgent, setNewNodeAgent] = useState("gaia");
  const [advancedPipelineJson, setAdvancedPipelineJson] = useState("");
  const [advancedNodeJson, setAdvancedNodeJson] = useState("");
  const [pipelineParseError, setPipelineParseError] = useState<string | null>(null);
  const [nodeParseError, setNodeParseError] = useState<string | null>(null);

  const graphQuery = useQuery({
    queryKey: ["graph", graphId],
    queryFn: () => getGraph(graphId),
    enabled: graphId !== "new",
  });

  useEffect(() => {
    if (graphId === "new") {
      const graph = defaultGraph();
      loadGraph(graph);
      setAdvancedPipelineJson(JSON.stringify(graph.pipeline, null, 2));
      return;
    }
    if (graphQuery.data) {
      loadGraph(graphQuery.data);
      setAdvancedPipelineJson(JSON.stringify(graphQuery.data.pipeline, null, 2));
    }
  }, [graphId, graphQuery.data, loadGraph]);

  useEffect(() => {
    setAdvancedPipelineJson(JSON.stringify(draft.pipeline, null, 2));
  }, [draft.pipeline]);

  useBeforeUnload((event) => {
    if (!dirty) {
      return;
    }
    event.preventDefault();
  });

  const selectedNode = useMemo(
    () => draft.pipeline.nodes.find((node) => node.id === selectedNodeId) ?? null,
    [draft.pipeline.nodes, selectedNodeId],
  );

  useEffect(() => {
    setAdvancedNodeJson(selectedNode ? JSON.stringify(selectedNode, null, 2) : "");
    setNodeParseError(null);
  }, [selectedNode]);

  const saveMutation = useMutation({
    mutationFn: async () => {
      const payload = snapshot();
      return graphId === "new" ? createGraph(payload) : updateGraph(graphId, { graph_id: graphId, ...payload });
    },
    onSuccess: async (graph) => {
      loadGraph(graph);
      await queryClient.invalidateQueries({ queryKey: ["graphs"] });
      await queryClient.invalidateQueries({ queryKey: ["graph", graph.meta.id] });
      pushToast({ tone: "success", title: "Graph saved", description: `${graph.pipeline.name} is up to date.` });
      if (graph.meta.id !== graphId) {
        navigate(`/graphs/${graph.meta.id}/edit`);
      }
    },
    onError: (error: Error) => {
      pushToast({ tone: "danger", title: "Save failed", description: error.message });
    },
  });

  const validateMutation = useMutation({
    mutationFn: async () => validateGraph(snapshot().pipeline),
    onSuccess: () => {
      pushToast({ tone: "success", title: "Validation passed", description: "PipelineSpec validation completed cleanly." });
    },
    onError: (error: Error) => {
      pushToast({ tone: "danger", title: "Validation failed", description: error.message });
    },
  });

  const runMutation = useMutation({
    mutationFn: async () => createRun({ graph_id: graphId !== "new" ? graphId : undefined, pipeline: snapshot().pipeline }),
    onSuccess: async (payload) => {
      await queryClient.invalidateQueries({ queryKey: ["runs"] });
      pushToast({ tone: "success", title: "Run started", description: `Opened run ${payload.run.id}.` });
      navigate(`/runs/${payload.run.id}`);
    },
    onError: (error: Error) => {
      pushToast({ tone: "danger", title: "Run start failed", description: error.message });
    },
  });

  const importMutation = useMutation({
    mutationFn: async (path: string) => importGraph(path),
    onSuccess: (pipeline) => {
      loadGraph({
        ...draft,
        pipeline,
        meta: {
          ...draft.meta,
          layout: {},
        },
      });
      setAdvancedPipelineJson(JSON.stringify(pipeline, null, 2));
      setImportPath("");
      pushToast({ tone: "success", title: "Graph imported", description: "Imported pipeline is ready in the editor." });
    },
    onError: (error: Error) => {
      pushToast({ tone: "danger", title: "Import failed", description: error.message });
    },
  });

  const exportMutation = useMutation({
    mutationFn: async () => exportGraphPython(graphId),
    onSuccess: (payload) => {
      setExportContent(payload.content);
      pushToast({ tone: "success", title: "Python export ready", description: payload.filename });
    },
    onError: (error: Error) => {
      pushToast({ tone: "danger", title: "Export failed", description: error.message });
    },
  });

  useEffect(() => {
    function isEditableTarget(target: EventTarget | null) {
      const element = target as HTMLElement | null;
      if (!element) {
        return false;
      }
      return (
        element.tagName === "INPUT" ||
        element.tagName === "TEXTAREA" ||
        element.isContentEditable ||
        Boolean(element.closest(".monaco-editor"))
      );
    }

    function onKeyDown(event: KeyboardEvent) {
      const isMetaSave = (event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s";
      const isQuickAdd = !event.ctrlKey && !event.metaKey && !event.altKey && event.shiftKey && event.key.toLowerCase() === "a";
      const isDelete = event.key === "Delete" || event.key === "Backspace";
      const isFitView = event.key.toLowerCase() === "f" && event.shiftKey;
      if (isMetaSave) {
        event.preventDefault();
        void saveMutation.mutateAsync();
      } else if (isQuickAdd && !isEditableTarget(event.target)) {
        event.preventDefault();
        addNodeWithTemplate({ id: newNodeId.trim() || undefined, agent: newNodeAgent });
      } else if (isDelete && selectedNodeId) {
        if (!isEditableTarget(event.target)) {
          event.preventDefault();
          removeSelectedNode();
        }
      } else if (isFitView) {
        event.preventDefault();
        void reactFlow.fitView({ padding: 0.18, duration: 240 });
      }
    }

    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [addNodeWithTemplate, newNodeAgent, newNodeId, reactFlow, removeSelectedNode, saveMutation, selectedNodeId]);

  if (graphId !== "new" && graphQuery.isLoading) {
    return <LoadingState>Loading graph...</LoadingState>;
  }
  if (graphQuery.error) {
    return <ErrorState message={graphQuery.error.message} />;
  }

  const dependencyOptions = draft.pipeline.nodes.filter((node) => node.id !== selectedNodeId);
  const validationState = validateMutation.data;

  return (
    <div className="page-stack">
      <PageHeader
        eyebrow="Authoring"
        title={draft.pipeline.name}
        description="Structured graph authoring first, with advanced JSON isolated to a non-destructive utility area."
        meta={<span className={`status-badge ${dirty ? "status-running" : "status-completed"}`}>{dirty ? "dirty" : "saved"}</span>}
        actions={
          <>
            <button className="button primary" disabled={saveMutation.isPending} onClick={() => saveMutation.mutate()} type="button">
              {saveMutation.isPending ? "Saving..." : "Save"}
            </button>
            <button className="button" disabled={validateMutation.isPending} onClick={() => validateMutation.mutate()} type="button">
              {validateMutation.isPending ? "Validating..." : "Validate"}
            </button>
            <button className="button" disabled={runMutation.isPending} onClick={() => runMutation.mutate()} type="button">
              {runMutation.isPending ? "Starting..." : "Run"}
            </button>
          </>
        }
      />

      {dirty ? (
        <InlineNotice tone="warning">
          You have unsaved graph changes. Save before leaving or starting a comparison run.
        </InlineNotice>
      ) : null}

      <SplitPane
        aside={
          <div className="inspector-sections">
            <PageSection
              title="Inspector"
              description="Structured editing for graph-level settings and selected node details."
              actions={
                <SegmentedControl
                  options={[
                    { label: "Structured", value: "structured" },
                    { label: "Advanced", value: "advanced" },
                  ]}
                  value={editorMode}
                  onChange={setEditorMode}
                />
              }
            >
              {editorMode === "structured" ? (
                <div className="inspector-sections">
                  <GraphSettingsPanel
                    description={draft.pipeline.description ?? ""}
                    name={draft.pipeline.name}
                    onMetaChange={updateGraphMeta}
                    onPipelineSettingChange={updatePipelineSetting}
                    pipeline={draft.pipeline}
                  />
                  {selectedNode ? (
                    <NodeInspectorPanel
                      dependencyOptions={dependencyOptions.map((node) => node.id)}
                      node={selectedNode}
                      onDependenciesChange={setSelectedNodeDependencies}
                      onNodeChange={updateSelectedNode}
                      onRemove={removeSelectedNode}
                    />
                  ) : (
                    <InlineNotice tone="info">Select a node from the canvas to edit its fields.</InlineNotice>
                  )}
                </div>
              ) : (
                <div className="inspector-sections">
                  <PageSection title="Advanced node JSON" description="Apply raw node JSON only after it parses cleanly.">
                    {selectedNode ? (
                      <>
                        <Editor
                          defaultLanguage="json"
                          height="280px"
                          options={{ minimap: { enabled: false }, fontSize: 13 }}
                          value={advancedNodeJson}
                          onChange={(value) => setAdvancedNodeJson(value ?? "")}
                        />
                        {nodeParseError ? <InlineNotice tone="danger">{nodeParseError}</InlineNotice> : null}
                        <button
                          className="button"
                          onClick={() => {
                            try {
                              updateSelectedNode(JSON.parse(advancedNodeJson) as PipelineNode);
                              setNodeParseError(null);
                              pushToast({ tone: "success", title: "Node JSON applied" });
                            } catch (error) {
                              setNodeParseError((error as Error).message);
                            }
                          }}
                          type="button"
                        >
                          Apply node JSON
                        </button>
                      </>
                    ) : (
                      <InlineNotice tone="info">Select a node before using advanced node JSON.</InlineNotice>
                    )}
                  </PageSection>
                </div>
              )}
            </PageSection>
          </div>
        }
      >
        <div className="detail-stack">
          <PageSection
            title="Graph canvas"
            description="Visual layout, dependency wiring, and guided node insertion."
            actions={
              <div className="toolbar">
                <button className="button" onClick={() => reactFlow.fitView({ padding: 0.18, duration: 240 })} type="button">
                  Fit view
                </button>
                <span className="muted">Shortcuts: Ctrl/Cmd+S save, Shift+A add node, Delete remove, Shift+F fit</span>
              </div>
            }
          >
            <div className="flow-panel flow-panel-editor">
              <ReactFlow
                fitView
                edges={flowEdges}
                nodes={flowNodes}
                nodeTypes={nodeTypes}
                onConnect={onConnect}
                onEdgesChange={onEdgesChange}
                onNodeClick={(_, node) => setSelectedNodeId(node.id)}
                onNodesChange={onNodesChange}
                proOptions={{ hideAttribution: true }}
              >
                <Background gap={24} />
                <MiniMap />
                <Controls />
              </ReactFlow>
            </div>
            <div className="inspector-grid">
              <label className="field">
                <span className="field-label">New node id</span>
                <input placeholder="node_review" value={newNodeId} onChange={(event) => setNewNodeId(event.target.value)} />
              </label>
              <label className="field">
                <span className="field-label">New node agent</span>
                <select value={newNodeAgent} onChange={(event) => setNewNodeAgent(event.target.value)}>
                  <option value="gaia">gaia</option>
                </select>
              </label>
            </div>
            <div className="toolbar">
              <button
                className="button"
                onClick={() => {
                  addNodeWithTemplate({ id: newNodeId.trim() || undefined, agent: newNodeAgent });
                  setNewNodeId("");
                }}
                type="button"
              >
                Add node
              </button>
            </div>
          </PageSection>

          <div className="utility-grid">
            <PageSection title="Import" description="Pull an existing pipeline from disk without browser prompts.">
              <label className="field">
                <span className="field-label">Pipeline path</span>
                <input
                  placeholder="examples/graph_optimization_rounds.py"
                  value={importPath}
                  onChange={(event) => setImportPath(event.target.value)}
                />
              </label>
              <button
                className="button"
                disabled={!importPath.trim() || importMutation.isPending}
                onClick={() => importMutation.mutate(importPath)}
                type="button"
              >
                {importMutation.isPending ? "Importing..." : "Import graph"}
              </button>
            </PageSection>

            <PageSection title="Validation" description="Non-destructive checks with explicit status feedback.">
              {validationState ? (
                <InlineNotice tone={validationState.valid ? "success" : "danger"}>
                  {validationState.valid ? "PipelineSpec validation passed." : "Validation returned an invalid result."}
                </InlineNotice>
              ) : (
                <InlineNotice tone="info">Run validation before saving or executing a new draft.</InlineNotice>
              )}
            </PageSection>

            <PageSection title="Export" description="Generate Python after the graph has a persisted id.">
              <button
                className="button"
                disabled={graphId === "new" || exportMutation.isPending}
                onClick={() => exportMutation.mutate()}
                type="button"
              >
                {exportMutation.isPending ? "Exporting..." : "Export Python"}
              </button>
              {exportContent ? <pre className="code-block">{exportContent}</pre> : null}
            </PageSection>
          </div>

          <PageSection title="Advanced pipeline JSON" description="Keep raw pipeline editing behind an explicit apply step.">
            <Editor
              defaultLanguage="json"
              height="320px"
              options={{ minimap: { enabled: false }, fontSize: 13 }}
              value={advancedPipelineJson}
              onChange={(value) => setAdvancedPipelineJson(value ?? "")}
            />
            {pipelineParseError ? <InlineNotice tone="danger">{pipelineParseError}</InlineNotice> : null}
            <div className="toolbar">
              <button
                className="button"
                onClick={() => {
                  try {
                    applyPipelineJson(advancedPipelineJson);
                    setPipelineParseError(null);
                    pushToast({ tone: "success", title: "Pipeline JSON applied" });
                  } catch (error) {
                    setPipelineParseError((error as Error).message);
                  }
                }}
                type="button"
              >
                Apply pipeline JSON
              </button>
            </div>
          </PageSection>
        </div>
      </SplitPane>
    </div>
  );
}

function GraphSettingsPanel({
  name,
  description,
  pipeline,
  onMetaChange,
  onPipelineSettingChange,
}: {
  name: string;
  description: string;
  pipeline: {
    working_dir?: string;
    concurrency?: number;
    fail_fast?: boolean;
    max_iterations?: number;
    scratchboard?: boolean;
    use_worktree?: boolean;
  };
  onMetaChange: (field: "name" | "description", value: string) => void;
  onPipelineSettingChange: (
    field: "working_dir" | "concurrency" | "fail_fast" | "max_iterations" | "scratchboard" | "use_worktree",
    value: string | number | boolean,
  ) => void;
}) {
  return (
    <PageSection title="Graph settings" description="Pipeline identity and execution defaults.">
      <div className="field">
        <label className="field-label">Graph name</label>
        <input value={name} onChange={(event) => onMetaChange("name", event.target.value)} />
      </div>
      <div className="field">
        <label className="field-label">Description</label>
        <textarea value={description} onChange={(event) => onMetaChange("description", event.target.value)} />
      </div>
      <div className="inspector-grid">
        <label className="field">
          <span className="field-label">Working dir</span>
          <input
            value={pipeline.working_dir ?? "."}
            onChange={(event) => onPipelineSettingChange("working_dir", event.target.value)}
          />
        </label>
        <label className="field">
          <span className="field-label">Concurrency</span>
          <input
            min={1}
            type="number"
            value={pipeline.concurrency ?? 1}
            onChange={(event) => onPipelineSettingChange("concurrency", Number(event.target.value))}
          />
        </label>
        <label className="field">
          <span className="field-label">Max iterations</span>
          <input
            min={1}
            type="number"
            value={pipeline.max_iterations ?? 1}
            onChange={(event) => onPipelineSettingChange("max_iterations", Number(event.target.value))}
          />
        </label>
      </div>
      <div className="checkbox-grid">
        <label className="checkbox-item">
          <input
            checked={Boolean(pipeline.fail_fast)}
            onChange={(event) => onPipelineSettingChange("fail_fast", event.target.checked)}
            type="checkbox"
          />
          Fail fast
        </label>
        <label className="checkbox-item">
          <input
            checked={Boolean(pipeline.scratchboard)}
            onChange={(event) => onPipelineSettingChange("scratchboard", event.target.checked)}
            type="checkbox"
          />
          Scratchboard
        </label>
        <label className="checkbox-item">
          <input
            checked={Boolean(pipeline.use_worktree)}
            onChange={(event) => onPipelineSettingChange("use_worktree", event.target.checked)}
            type="checkbox"
          />
          Worktree
        </label>
      </div>
    </PageSection>
  );
}

function NodeInspectorPanel({
  node,
  dependencyOptions,
  onNodeChange,
  onDependenciesChange,
  onRemove,
}: {
  node: PipelineNode;
  dependencyOptions: string[];
  onNodeChange: (node: PipelineNode) => void;
  onDependenciesChange: (dependsOn: string[]) => void;
  onRemove: () => void;
}) {
  return (
    <PageSection title="Node inspector" description="Basic, prompt, dependencies, and advanced execution surface.">
      <div className="field">
        <label className="field-label">Node id</label>
        <input value={node.id} onChange={(event) => onNodeChange({ ...node, id: event.target.value })} />
      </div>
      <div className="field">
        <label className="field-label">Agent</label>
        <input value={node.agent} onChange={(event) => onNodeChange({ ...node, agent: event.target.value })} />
      </div>
      <div className="field">
        <label className="field-label">Prompt</label>
        <textarea value={String(node.prompt ?? "")} onChange={(event) => onNodeChange({ ...node, prompt: event.target.value })} />
      </div>
      <div className="field compact">
        <span className="field-label">Dependencies</span>
        {dependencyOptions.length ? (
          <div className="checkbox-grid">
            {dependencyOptions.map((dependencyId) => {
              const checked = node.depends_on.includes(dependencyId);
              return (
                <label className="checkbox-item" key={dependencyId}>
                  <input
                    checked={checked}
                    onChange={(event) => {
                      if (event.target.checked) {
                        onDependenciesChange([...node.depends_on, dependencyId]);
                      } else {
                        onDependenciesChange(node.depends_on.filter((item) => item !== dependencyId));
                      }
                    }}
                    type="checkbox"
                  />
                  {dependencyId}
                </label>
              );
            })}
          </div>
        ) : (
          <InlineNotice tone="info">No other nodes available for dependencies.</InlineNotice>
        )}
      </div>
      <button className="button danger" onClick={onRemove} type="button">
        Remove node
      </button>
    </PageSection>
  );
}
