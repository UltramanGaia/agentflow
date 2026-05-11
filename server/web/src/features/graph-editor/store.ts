import type { Node } from "reactflow";
import {
  applyEdgeChanges,
  applyNodeChanges,
  type Connection,
  type Edge,
  type EdgeChange,
  type NodeChange,
} from "reactflow";
import { create } from "zustand";
import type { AgentNodeData } from "../../components/graph/AgentNode";
import type { GraphView, PipelineNode, PipelineSpec } from "../../types/api";
import {
  applyConnection,
  cloneGraph,
  defaultGraph,
  ensureLayout,
  normalizeNode,
  removeConnection,
  renameNode,
  toFlowEdges,
  toFlowNodes,
} from "./mappers";

interface GraphEditorStore {
  draft: GraphView;
  flowNodes: Node<AgentNodeData>[];
  flowEdges: Edge[];
  selectedNodeId: string | null;
  jsonMode: boolean;
  dirty: boolean;
  exportContent: string;
  loadGraph: (graph: GraphView) => void;
  setSelectedNodeId: (nodeId: string | null) => void;
  setJsonMode: (jsonMode: boolean) => void;
  setExportContent: (content: string) => void;
  updateGraphMeta: (field: "name" | "description", value: string) => void;
  updatePipelineSetting: (
    field: "working_dir" | "concurrency" | "fail_fast" | "max_iterations" | "scratchboard" | "use_worktree",
    value: string | number | boolean,
  ) => void;
  updateSelectedNode: (rawNode: PipelineNode) => void;
  setSelectedNodeDependencies: (dependsOn: string[]) => void;
  applyPipelineJson: (jsonText: string) => void;
  addNode: () => void;
  addNodeWithTemplate: (template?: Partial<PipelineNode>) => void;
  removeSelectedNode: () => void;
  onNodesChange: (changes: NodeChange[]) => void;
  onEdgesChange: (changes: EdgeChange[]) => void;
  onConnect: (connection: Connection) => void;
  removeEdge: (edgeId: string) => void;
  snapshot: () => { pipeline: PipelineSpec; layout: Record<string, { x: number; y: number }> };
}

function buildState(graph: GraphView, selectedNodeId?: string | null) {
  const draft = cloneGraph(graph);
  ensureLayout(draft);
  const nextSelectedNodeId = selectedNodeId ?? draft.pipeline.nodes[0]?.id ?? null;
  return {
    draft,
    selectedNodeId: nextSelectedNodeId,
    flowNodes: toFlowNodes(draft, nextSelectedNodeId),
    flowEdges: toFlowEdges(draft.pipeline),
  };
}

export const useGraphEditorStore = create<GraphEditorStore>((set, get) => ({
  draft: defaultGraph(),
  flowNodes: [],
  flowEdges: [],
  selectedNodeId: null,
  jsonMode: false,
  dirty: false,
  exportContent: "",
  loadGraph: (graph) =>
    set(() => ({
      ...buildState(graph),
      jsonMode: false,
      dirty: false,
      exportContent: "",
    })),
  setSelectedNodeId: (selectedNodeId) =>
    set((state) => ({
      selectedNodeId,
      flowNodes: toFlowNodes(state.draft, selectedNodeId),
    })),
  setJsonMode: (jsonMode) => set(() => ({ jsonMode })),
  setExportContent: (exportContent) => set(() => ({ exportContent })),
  updateGraphMeta: (field, value) =>
    set((state) => {
      const draft = cloneGraph(state.draft);
      draft.pipeline[field] = value;
      if (field === "name") {
        draft.meta.name = value;
      } else {
        draft.meta.description = value;
      }
      return {
        draft,
        dirty: true,
        flowNodes: toFlowNodes(draft, state.selectedNodeId),
      };
    }),
  updatePipelineSetting: (field, value) =>
    set((state) => {
      const draft = cloneGraph(state.draft);
      switch (field) {
        case "working_dir":
          draft.pipeline.working_dir = String(value);
          break;
        case "concurrency":
          draft.pipeline.concurrency = Number(value);
          break;
        case "max_iterations":
          draft.pipeline.max_iterations = Number(value);
          break;
        case "fail_fast":
          draft.pipeline.fail_fast = Boolean(value);
          break;
        case "scratchboard":
          draft.pipeline.scratchboard = Boolean(value);
          break;
        case "use_worktree":
          draft.pipeline.use_worktree = Boolean(value);
          break;
      }
      return {
        draft,
        dirty: true,
        flowNodes: toFlowNodes(draft, state.selectedNodeId),
      };
    }),
  updateSelectedNode: (rawNode) =>
    set((state) => {
      if (!state.selectedNodeId) {
        return state;
      }
      const draft = cloneGraph(state.draft);
      const normalizedNode = normalizeNode(rawNode);
      const index = draft.pipeline.nodes.findIndex((node) => node.id === state.selectedNodeId);
      if (index < 0) {
        return state;
      }
      const previousId = draft.pipeline.nodes[index].id;
      draft.pipeline.nodes[index] = normalizedNode;
      renameNode(draft.pipeline, draft.meta.layout, previousId, normalizedNode.id);
      return {
        draft,
        selectedNodeId: normalizedNode.id,
        dirty: true,
        flowNodes: toFlowNodes(draft, normalizedNode.id),
        flowEdges: toFlowEdges(draft.pipeline),
      };
    }),
  setSelectedNodeDependencies: (dependsOn) =>
    set((state) => {
      if (!state.selectedNodeId) {
        return state;
      }
      const draft = cloneGraph(state.draft);
      const selectedNode = draft.pipeline.nodes.find((node) => node.id === state.selectedNodeId);
      if (!selectedNode) {
        return state;
      }
      selectedNode.depends_on = dependsOn.filter((dependency) => dependency !== selectedNode.id);
      return {
        draft,
        dirty: true,
        flowNodes: toFlowNodes(draft, state.selectedNodeId),
        flowEdges: toFlowEdges(draft.pipeline),
      };
    }),
  applyPipelineJson: (jsonText) =>
    set((state) => {
      const draft = cloneGraph(state.draft);
      draft.pipeline = JSON.parse(jsonText) as PipelineSpec;
      ensureLayout(draft);
      const selectedNodeId =
        draft.pipeline.nodes.find((node) => node.id === state.selectedNodeId)?.id ?? draft.pipeline.nodes[0]?.id ?? null;
      return {
        draft,
        selectedNodeId,
        dirty: true,
        flowNodes: toFlowNodes(draft, selectedNodeId),
        flowEdges: toFlowEdges(draft.pipeline),
      };
    }),
  addNodeWithTemplate: (template) =>
    set((state) => {
      const draft = cloneGraph(state.draft);
      const nextId = template?.id?.trim() || `node_${draft.pipeline.nodes.length + 1}`;
      draft.pipeline.nodes.push(
        normalizeNode({
          id: nextId,
          agent: template?.agent ?? "codex",
          prompt: template?.prompt ?? "",
          depends_on: template?.depends_on ?? [],
          ...template,
        }),
      );
      ensureLayout(draft);
      return {
        draft,
        selectedNodeId: nextId,
        dirty: true,
        flowNodes: toFlowNodes(draft, nextId),
        flowEdges: toFlowEdges(draft.pipeline),
      };
    }),
  addNode: () =>
    set((state) => {
      const draft = cloneGraph(state.draft);
      const nextId = `node_${draft.pipeline.nodes.length + 1}`;
      draft.pipeline.nodes.push({
        id: nextId,
        agent: "codex",
        prompt: "",
        depends_on: [],
      });
      ensureLayout(draft);
      return {
        draft,
        selectedNodeId: nextId,
        dirty: true,
        flowNodes: toFlowNodes(draft, nextId),
        flowEdges: toFlowEdges(draft.pipeline),
      };
    }),
  removeSelectedNode: () =>
    set((state) => {
      if (!state.selectedNodeId) {
        return state;
      }
      const draft = cloneGraph(state.draft);
      draft.pipeline.nodes = draft.pipeline.nodes.filter((node) => node.id !== state.selectedNodeId);
      draft.pipeline.nodes.forEach((node) => {
        node.depends_on = node.depends_on.filter((dependency) => dependency !== state.selectedNodeId);
      });
      delete draft.meta.layout[state.selectedNodeId];
      const selectedNodeId = draft.pipeline.nodes[0]?.id ?? null;
      return {
        draft,
        selectedNodeId,
        dirty: true,
        flowNodes: toFlowNodes(draft, selectedNodeId),
        flowEdges: toFlowEdges(draft.pipeline),
      };
    }),
  onNodesChange: (changes) =>
    set((state) => {
      const flowNodes = applyNodeChanges(changes, state.flowNodes);
      const draft = cloneGraph(state.draft);
      flowNodes.forEach((node) => {
        draft.meta.layout[node.id] = {
          x: node.position.x,
          y: node.position.y,
        };
      });
      const selectedNodeId = flowNodes.find((node) => node.selected)?.id ?? state.selectedNodeId;
      return {
        draft,
        selectedNodeId,
        flowNodes: toFlowNodes(draft, selectedNodeId),
        flowEdges: state.flowEdges,
        dirty: true,
      };
    }),
  onEdgesChange: (changes) =>
    set((state) => {
      const draft = cloneGraph(state.draft);
      for (const change of changes) {
        if (change.type === "remove") {
          const edge = state.flowEdges.find((item) => item.id === change.id);
          if (edge) {
            removeConnection(draft.pipeline, edge);
          }
        }
      }
      applyEdgeChanges(changes, state.flowEdges);
      return {
        draft,
        flowNodes: state.flowNodes,
        flowEdges: toFlowEdges(draft.pipeline),
        dirty: true,
      };
    }),
  onConnect: (connection) =>
    set((state) => {
      const draft = cloneGraph(state.draft);
      applyConnection(draft.pipeline, connection);
      return {
        draft,
        flowNodes: state.flowNodes,
        flowEdges: toFlowEdges(draft.pipeline),
        dirty: true,
      };
    }),
  removeEdge: (edgeId) =>
    set((state) => {
      const draft = cloneGraph(state.draft);
      const edge = state.flowEdges.find((item) => item.id === edgeId);
      if (!edge) {
        return state;
      }
      removeConnection(draft.pipeline, edge);
      return {
        draft,
        flowNodes: state.flowNodes,
        flowEdges: toFlowEdges(draft.pipeline),
        dirty: true,
      };
    }),
  snapshot: () => {
    const state = get();
    return {
      pipeline: structuredClone(state.draft.pipeline),
      layout: structuredClone(state.draft.meta.layout),
    };
  },
}));
