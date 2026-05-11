import { beforeEach, describe, expect, it } from "vitest";
import { useGraphEditorStore } from "./store";
import type { GraphView, PipelineSpec } from "../../types/api";

function makeGraph(overrides?: Partial<GraphView>): GraphView {
  return {
    meta: {
      id: "test-graph",
      name: "test-graph",
      description: "test desc",
      created_at: "2024-01-01T00:00:00Z",
      updated_at: "2024-01-01T00:00:00Z",
      layout: {},
    },
    pipeline: {
      name: "test-graph",
      description: "test desc",
      nodes: [
        { id: "plan", agent: "codex", prompt: "Plan the work.", depends_on: [] },
        { id: "impl", agent: "claude", prompt: "Implement.", depends_on: ["plan"] },
      ],
    },
    ...overrides,
  };
}

beforeEach(() => {
  useGraphEditorStore.getState().loadGraph(makeGraph());
});

describe("loadGraph", () => {
  it("initializes draft, flow nodes, and flow edges from graph", () => {
    const state = useGraphEditorStore.getState();
    
    expect(state.draft.meta.id).toBe("test-graph");
    expect(state.draft.pipeline.nodes).toHaveLength(2);
    expect(state.flowNodes).toHaveLength(2);
    expect(state.flowEdges).toHaveLength(1);
    expect(state.dirty).toBe(false);
    expect(state.jsonMode).toBe(false);
  });

  it("selects the first node by default", () => {
    const state = useGraphEditorStore.getState();
    
    expect(state.selectedNodeId).toBe("plan");
  });

  it("selects the first node when graph has no selection", () => {
    useGraphEditorStore.getState().loadGraph(makeGraph());
    
    const state = useGraphEditorStore.getState();
    expect(state.selectedNodeId).toBe("plan");
  });
});

describe("setSelectedNodeId", () => {
  it("updates selected node and re-renders flow nodes", () => {
    useGraphEditorStore.getState().setSelectedNodeId("impl");
    
    const state = useGraphEditorStore.getState();
    expect(state.selectedNodeId).toBe("impl");
    expect(state.flowNodes.find((n) => n.id === "impl")?.selected).toBe(true);
    expect(state.flowNodes.find((n) => n.id === "plan")?.selected).toBe(false);
  });

  it("allows deselecting by passing null", () => {
    useGraphEditorStore.getState().setSelectedNodeId(null);
    
    expect(useGraphEditorStore.getState().selectedNodeId).toBeNull();
  });
});

describe("updateGraphMeta", () => {
  it("updates graph name", () => {
    useGraphEditorStore.getState().updateGraphMeta("name", "renamed-graph");
    
    const state = useGraphEditorStore.getState();
    expect(state.draft.pipeline.name).toBe("renamed-graph");
    expect(state.draft.meta.name).toBe("renamed-graph");
    expect(state.dirty).toBe(true);
  });

  it("updates graph description", () => {
    useGraphEditorStore.getState().updateGraphMeta("description", "new description");
    
    const state = useGraphEditorStore.getState();
    expect(state.draft.pipeline.description).toBe("new description");
    expect(state.draft.meta.description).toBe("new description");
    expect(state.dirty).toBe(true);
  });
});

describe("updateSelectedNode", () => {
  it("updates the selected node properties", () => {
    useGraphEditorStore.getState().setSelectedNodeId("plan");
    useGraphEditorStore.getState().updateSelectedNode({
      id: "plan",
      agent: "pi",
      prompt: "New prompt",
      depends_on: [],
    });

    const state = useGraphEditorStore.getState();
    const node = state.draft.pipeline.nodes.find((n) => n.id === "plan");
    expect(node?.agent).toBe("pi");
    expect(node?.prompt).toBe("New prompt");
    expect(state.dirty).toBe(true);
  });

  it("renames a node and updates all references", () => {
    useGraphEditorStore.getState().setSelectedNodeId("plan");
    useGraphEditorStore.getState().updateSelectedNode({
      id: "planning",
      agent: "codex",
      prompt: "Plan the work.",
      depends_on: [],
    });

    const state = useGraphEditorStore.getState();
    expect(state.selectedNodeId).toBe("planning");
    expect(state.draft.pipeline.nodes[0].id).toBe("planning");
    expect(state.draft.pipeline.nodes[1].depends_on).toContain("planning");
  });

  it("does nothing when no node is selected", () => {
    useGraphEditorStore.getState().setSelectedNodeId(null);
    const before = useGraphEditorStore.getState().draft;
    
    useGraphEditorStore.getState().updateSelectedNode({
      id: "plan",
      agent: "codex",
      prompt: "",
      depends_on: [],
    });

    const after = useGraphEditorStore.getState().draft;
    expect(before).toEqual(after);
  });
});

describe("addNode", () => {
  it("adds a new node with auto-generated ID", () => {
    useGraphEditorStore.getState().addNode();
    
    const state = useGraphEditorStore.getState();
    expect(state.draft.pipeline.nodes).toHaveLength(3);
    expect(state.draft.pipeline.nodes[2].id).toBe("node_3");
    expect(state.selectedNodeId).toBe("node_3");
    expect(state.dirty).toBe(true);
  });
});

describe("removeSelectedNode", () => {
  it("removes the selected node and its dependencies", () => {
    useGraphEditorStore.getState().setSelectedNodeId("plan");
    useGraphEditorStore.getState().removeSelectedNode();
    
    const state = useGraphEditorStore.getState();
    expect(state.draft.pipeline.nodes).toHaveLength(1);
    expect(state.draft.pipeline.nodes[0].id).toBe("impl");
    expect(state.draft.pipeline.nodes[0].depends_on).toEqual([]);
    expect(state.dirty).toBe(true);
  });

  it("selects the first remaining node after removal", () => {
    useGraphEditorStore.getState().setSelectedNodeId("plan");
    useGraphEditorStore.getState().removeSelectedNode();
    
    expect(useGraphEditorStore.getState().selectedNodeId).toBe("impl");
  });

  it("does nothing when no node is selected", () => {
    useGraphEditorStore.getState().setSelectedNodeId(null);
    const countBefore = useGraphEditorStore.getState().draft.pipeline.nodes.length;
    
    useGraphEditorStore.getState().removeSelectedNode();
    
    expect(useGraphEditorStore.getState().draft.pipeline.nodes).toHaveLength(countBefore);
  });
});

describe("applyPipelineJson", () => {
  it("replaces the pipeline from JSON text", () => {
    const newPipeline: PipelineSpec = {
      name: "from-json",
      nodes: [{ id: "step1", agent: "pi", prompt: "Go", depends_on: [] }],
    };

    useGraphEditorStore.getState().applyPipelineJson(JSON.stringify(newPipeline));
    
    const state = useGraphEditorStore.getState();
    expect(state.draft.pipeline.name).toBe("from-json");
    expect(state.draft.pipeline.nodes).toHaveLength(1);
    expect(state.dirty).toBe(true);
  });

  it("keeps selection on matching node ID", () => {
    const newPipeline: PipelineSpec = {
      name: "from-json",
      nodes: [{ id: "plan", agent: "pi", prompt: "Go", depends_on: [] }],
    };

    useGraphEditorStore.getState().setSelectedNodeId("plan");
    useGraphEditorStore.getState().applyPipelineJson(JSON.stringify(newPipeline));
    
    expect(useGraphEditorStore.getState().selectedNodeId).toBe("plan");
  });
});

describe("onConnect", () => {
  it("adds a dependency edge", () => {
    useGraphEditorStore.getState().onConnect({ source: "impl", target: "plan" });
    
    const state = useGraphEditorStore.getState();
    const planNode = state.draft.pipeline.nodes.find((n) => n.id === "plan");
    expect(planNode?.depends_on).toContain("impl");
    expect(state.dirty).toBe(true);
  });
});

describe("snapshot", () => {
  it("returns a deep clone of pipeline and layout", () => {
    const snap = useGraphEditorStore.getState().snapshot();
    
    expect(snap.pipeline).toEqual(useGraphEditorStore.getState().draft.pipeline);
    expect(snap.layout).toEqual(useGraphEditorStore.getState().draft.meta.layout);
    expect(snap.pipeline).not.toBe(useGraphEditorStore.getState().draft.pipeline);
  });
});

describe("setJsonMode", () => {
  it("toggles JSON mode", () => {
    useGraphEditorStore.getState().setJsonMode(true);
    expect(useGraphEditorStore.getState().jsonMode).toBe(true);

    useGraphEditorStore.getState().setJsonMode(false);
    expect(useGraphEditorStore.getState().jsonMode).toBe(false);
  });
});

describe("setExportContent", () => {
  it("stores export content string", () => {
    useGraphEditorStore.getState().setExportContent("exported content");
    expect(useGraphEditorStore.getState().exportContent).toBe("exported content");
  });
});
