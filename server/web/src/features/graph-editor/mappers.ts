import type { Connection, Edge, Node } from "reactflow";
import type { AgentNodeData } from "../../components/graph/AgentNode";
import type { GraphView, PipelineNode, PipelineSpec } from "../../types/api";

export interface EditorDraft {
  meta: GraphView["meta"];
  pipeline: PipelineSpec;
}

export function defaultGraph(): GraphView {
  return {
    meta: {
      id: "new",
      name: "new-graph",
      description: "",
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
      layout: {},
    },
    pipeline: {
      name: "new-graph",
      description: "",
      working_dir: ".",
      concurrency: 4,
      fail_fast: false,
      max_iterations: 10,
      scratchboard: false,
      use_worktree: false,
      nodes: [],
    },
  };
}

export function ensureLayout(draft: EditorDraft) {
  draft.pipeline.nodes.forEach((node, index) => {
    if (!draft.meta.layout[node.id]) {
      draft.meta.layout[node.id] = {
        x: 80 + (index % 3) * 260,
        y: 80 + Math.floor(index / 3) * 180,
      };
    }
  });
}

export function toFlowNodes(draft: EditorDraft, selectedNodeId: string | null, statusByNode?: Record<string, string>) {
  ensureLayout(draft);
  return draft.pipeline.nodes.map<Node<AgentNodeData>>((node) => ({
    id: node.id,
    type: "agentNode",
    position: draft.meta.layout[node.id],
    data: {
      title: node.id,
      agent: node.agent,
      status: statusByNode?.[node.id],
    },
    selected: node.id === selectedNodeId,
  }));
}

export function toFlowEdges(pipeline: PipelineSpec) {
  return pipeline.nodes.flatMap<Edge>((node) =>
    node.depends_on.map((dependency) => ({
      id: `${dependency}->${node.id}`,
      source: dependency,
      target: node.id,
      animated: false,
      type: "smoothstep",
    })),
  );
}

export function applyConnection(pipeline: PipelineSpec, connection: Connection) {
  if (!connection.source || !connection.target || connection.source === connection.target) {
    return;
  }
  const targetNode = pipeline.nodes.find((node) => node.id === connection.target);
  if (!targetNode) {
    return;
  }
  const dependsOn = new Set(targetNode.depends_on);
  dependsOn.add(connection.source);
  targetNode.depends_on = Array.from(dependsOn);
}

export function removeConnection(pipeline: PipelineSpec, edge: Edge) {
  const targetNode = pipeline.nodes.find((node) => node.id === edge.target);
  if (!targetNode) {
    return;
  }
  targetNode.depends_on = targetNode.depends_on.filter((dependency) => dependency !== edge.source);
}

export function renameNode(pipeline: PipelineSpec, layout: EditorDraft["meta"]["layout"], oldId: string, nextId: string) {
  if (oldId === nextId) {
    return;
  }
  pipeline.nodes.forEach((node) => {
    node.depends_on = node.depends_on.map((dependency) => (dependency === oldId ? nextId : dependency));
    if (node.id === oldId) {
      node.id = nextId;
    }
  });
  if (layout[oldId]) {
    layout[nextId] = layout[oldId];
    delete layout[oldId];
  }
}

export function cloneGraph(graph: GraphView): GraphView {
  return structuredClone(graph);
}

export function normalizeNode(raw: unknown): PipelineNode {
  const node = raw as Record<string, unknown>;
  return {
    ...node,
    id: String(node.id ?? ""),
    agent: String(node.agent ?? "gaia"),
    prompt: String(node.prompt ?? ""),
    depends_on: Array.isArray(node.depends_on) ? node.depends_on.map(String) : [],
  };
}
