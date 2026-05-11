import Editor from "@monaco-editor/react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo } from "react";
import ReactFlow, {
  Background,
  Controls,
  MiniMap,
  ReactFlowProvider,
  type NodeTypes,
} from "reactflow";
import { useBeforeUnload, useNavigate, useParams } from "react-router-dom";
import { AgentNode } from "../../components/graph/AgentNode";
import { ErrorState, LoadingState } from "../../components/feedback/States";
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
  const { graphId = "new" } = useParams();
  const {
    draft,
    flowNodes,
    flowEdges,
    selectedNodeId,
    jsonMode,
    dirty,
    exportContent,
    loadGraph,
    setSelectedNodeId,
    setJsonMode,
    setExportContent,
    updateGraphMeta,
    updateSelectedNode,
    applyPipelineJson,
    addNode,
    removeSelectedNode,
    onNodesChange,
    onEdgesChange,
    onConnect,
    removeEdge,
    snapshot,
  } = useGraphEditorStore();

  const graphQuery = useQuery({
    queryKey: ["graph", graphId],
    queryFn: () => getGraph(graphId),
    enabled: graphId !== "new",
  });

  useEffect(() => {
    if (graphId === "new") {
      loadGraph(defaultGraph());
      return;
    }
    if (graphQuery.data) {
      loadGraph(graphQuery.data);
    }
  }, [graphId, graphQuery.data, loadGraph]);

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

  const saveMutation = useMutation({
    mutationFn: async () => {
      const payload = snapshot();
      return graphId === "new"
        ? createGraph(payload)
        : updateGraph(graphId, { graph_id: graphId, ...payload });
    },
    onSuccess: async (graph) => {
      loadGraph(graph);
      await queryClient.invalidateQueries({ queryKey: ["graphs"] });
      await queryClient.invalidateQueries({ queryKey: ["graph", graph.meta.id] });
      if (graph.meta.id !== graphId) {
        navigate(`/graphs/${graph.meta.id}/edit`);
      }
    },
  });

  const validateMutation = useMutation({
    mutationFn: async () => validateGraph(snapshot().pipeline),
  });

  const runMutation = useMutation({
    mutationFn: async () => createRun({ graph_id: graphId !== "new" ? graphId : undefined, pipeline: snapshot().pipeline }),
    onSuccess: async (payload) => {
      await queryClient.invalidateQueries({ queryKey: ["runs"] });
      navigate(`/runs/${payload.run.id}`);
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
    },
  });

  const exportMutation = useMutation({
    mutationFn: async () => exportGraphPython(graphId),
    onSuccess: (payload) => {
      setExportContent(payload.content);
    },
  });

  if (graphId !== "new" && graphQuery.isLoading) {
    return <LoadingState>Loading graph...</LoadingState>;
  }
  if (graphQuery.error) {
    return <ErrorState message={graphQuery.error.message} />;
  }

  return (
    <div className="layout editor-layout">
      <section className="panel stack">
        <div className="section-head">
          <div>
            <h2>{draft.pipeline.name}</h2>
            <div className="muted">
              {draft.meta.id}
              {dirty ? " · unsaved changes" : ""}
            </div>
          </div>
          <div className="toolbar">
            <button className="button primary" onClick={() => saveMutation.mutate()} type="button">
              Save
            </button>
            <button className="button" onClick={() => validateMutation.mutate()} type="button">
              Validate
            </button>
            <button className="button" onClick={() => runMutation.mutate()} type="button">
              Run
            </button>
            <button className="button" onClick={() => setJsonMode(!jsonMode)} type="button">
              {jsonMode ? "Inspector Mode" : "JSON Mode"}
            </button>
          </div>
        </div>
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
        <div className="toolbar">
          <button className="button" onClick={() => addNode()} type="button">
            Add Node
          </button>
          <button
            className="button"
            onClick={() => {
              const path = window.prompt("Pipeline path to import");
              if (path) {
                importMutation.mutate(path);
              }
            }}
            type="button"
          >
            Import Python/JSON/YAML
          </button>
          <button
            className="button"
            onClick={() => {
              if (graphId === "new") {
                window.alert("Save the graph before exporting.");
                return;
              }
              exportMutation.mutate();
            }}
            type="button"
          >
            Export Python
          </button>
        </div>
        {validateMutation.isSuccess ? <div className="success-banner">PipelineSpec validation passed.</div> : null}
        {exportContent ? <pre>{exportContent}</pre> : null}
      </section>
      <section className="panel stack">
        {jsonMode ? (
          <div className="editor-column">
            <label>Pipeline JSON</label>
            <Editor
              defaultLanguage="json"
              height="640px"
              options={{ minimap: { enabled: false }, fontSize: 13 }}
              value={JSON.stringify(draft.pipeline, null, 2)}
              onChange={(value) => {
                if (value) {
                  applyPipelineJson(value);
                }
              }}
            />
          </div>
        ) : (
          <>
            <div className="field">
              <label>Graph Name</label>
              <input value={draft.pipeline.name} onChange={(event) => updateGraphMeta("name", event.target.value)} />
            </div>
            <div className="field">
              <label>Description</label>
              <textarea value={draft.pipeline.description ?? ""} onChange={(event) => updateGraphMeta("description", event.target.value)} />
            </div>
            {selectedNode ? (
              <>
                <SelectedNodeEditor node={selectedNode} onChange={updateSelectedNode} />
                <button className="button danger" onClick={() => removeSelectedNode()} type="button">
                  Remove Node
                </button>
                <div className="edge-list">
                  {flowEdges.map((edge) => (
                    <div className="edge-row" key={edge.id}>
                      {edge.source} → {edge.target}
                      <button className="button" onClick={() => removeEdge(edge.id)} type="button">
                        Remove
                      </button>
                    </div>
                  ))}
                </div>
              </>
            ) : (
              <div className="muted">Select a node to edit it.</div>
            )}
          </>
        )}
      </section>
    </div>
  );
}

function SelectedNodeEditor({ node, onChange }: { node: PipelineNode; onChange: (node: PipelineNode) => void }) {
  const jsonText = JSON.stringify(node, null, 2);
  return (
    <>
      <div className="field">
        <label>Selected Node</label>
        <input value={node.id} onChange={(event) => onChange({ ...node, id: event.target.value })} />
      </div>
      <div className="field">
        <label>Agent</label>
        <input value={node.agent} onChange={(event) => onChange({ ...node, agent: event.target.value })} />
      </div>
      <div className="editor-column">
        <label>Prompt</label>
        <Editor
          defaultLanguage="markdown"
          height="180px"
          options={{ minimap: { enabled: false }, fontSize: 13 }}
          value={String(node.prompt ?? "")}
          onChange={(value) => onChange({ ...node, prompt: value ?? "" })}
        />
      </div>
      <div className="editor-column">
        <label>Advanced JSON</label>
        <Editor
          defaultLanguage="json"
          height="320px"
          options={{ minimap: { enabled: false }, fontSize: 13 }}
          value={jsonText}
          onChange={(value) => {
            if (!value) {
              return;
            }
            onChange(JSON.parse(value) as PipelineNode);
          }}
        />
      </div>
    </>
  );
}
