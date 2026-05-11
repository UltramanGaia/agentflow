import { describe, expect, it } from "vitest";
import type { Edge } from "reactflow";
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
import type { GraphView, PipelineSpec } from "../../types/api";

function makeGraph(overrides?: Partial<GraphView>): GraphView {
  return {
    meta: {
      id: "test-graph",
      name: "test-graph",
      description: "",
      created_at: "2024-01-01T00:00:00Z",
      updated_at: "2024-01-01T00:00:00Z",
      layout: {},
    },
    pipeline: {
      name: "test-graph",
      nodes: [],
    },
    ...overrides,
  };
}

function makePipeline(overrides?: Partial<PipelineSpec>): PipelineSpec {
  return {
    name: "test-pipeline",
    nodes: [],
    ...overrides,
  };
}

describe("defaultGraph", () => {
  it("creates a new graph with default values", () => {
    const graph = defaultGraph();
    expect(graph.meta.id).toBe("new");
    expect(graph.meta.name).toBe("new-graph");
    expect(graph.pipeline.nodes).toEqual([]);
    expect(graph.pipeline.concurrency).toBe(4);
    expect(graph.pipeline.working_dir).toBe(".");
  });
});

describe("cloneGraph", () => {
  it("creates a deep copy of the graph", () => {
    const original = makeGraph({
      pipeline: {
        name: "original",
        nodes: [{ id: "node-1", agent: "gaia", prompt: "test", depends_on: [] }],
      },
    });
    const cloned = cloneGraph(original);
    
    expect(cloned).toEqual(original);
    expect(cloned).not.toBe(original);
    expect(cloned.pipeline.nodes[0]).not.toBe(original.pipeline.nodes[0]);
  });
});

describe("ensureLayout", () => {
  it("adds layout positions for nodes without positions", () => {
    const draft = {
      meta: {
        layout: {} as Record<string, { x: number; y: number }>,
      },
      pipeline: {
        nodes: [
          { id: "a", agent: "gaia", prompt: "", depends_on: [] },
          { id: "b", agent: "gaia", prompt: "", depends_on: [] },
          { id: "c", agent: "gaia", prompt: "", depends_on: [] },
          { id: "d", agent: "gaia", prompt: "", depends_on: [] },
        ],
      },
    } as const;

    ensureLayout(draft as { meta: { layout: Record<string, { x: number; y: number }> }; pipeline: { nodes: { id: string }[] } });
    
    expect(draft.meta.layout["a"]).toEqual({ x: 80, y: 80 });
    expect(draft.meta.layout["b"]).toEqual({ x: 340, y: 80 });
    expect(draft.meta.layout["c"]).toEqual({ x: 600, y: 80 });
    expect(draft.meta.layout["d"]).toEqual({ x: 80, y: 260 });
  });

  it("does not override existing positions", () => {
    const draft = {
      meta: {
        layout: { a: { x: 100, y: 200 } } as Record<string, { x: number; y: number }>,
      },
      pipeline: {
        nodes: [{ id: "a", agent: "gaia", prompt: "", depends_on: [] }],
      },
    };

    ensureLayout(draft as { meta: { layout: Record<string, { x: number; y: number }> }; pipeline: { nodes: { id: string }[] } });
    
    expect(draft.meta.layout["a"]).toEqual({ x: 100, y: 200 });
  });
});

describe("toFlowNodes", () => {
  it("converts pipeline nodes to React Flow nodes", () => {
    const draft = {
      meta: {
        layout: { "node-1": { x: 100, y: 200 } },
      },
      pipeline: {
        nodes: [{ id: "node-1", agent: "gaia", prompt: "test prompt", depends_on: [] }],
      },
    };

    const nodes = toFlowNodes(draft as { meta: { layout: Record<string, { x: number; y: number }> }; pipeline: { nodes: { id: string; agent: string; prompt: string; depends_on: string[] }[] } }, "node-1");
    
    expect(nodes).toHaveLength(1);
    expect(nodes[0].id).toBe("node-1");
    expect(nodes[0].type).toBe("agentNode");
    expect(nodes[0].position).toEqual({ x: 100, y: 200 });
    expect(nodes[0].data.title).toBe("node-1");
    expect(nodes[0].data.agent).toBe("gaia");
    expect(nodes[0].selected).toBe(true);
  });

  it("passes status to node data when provided", () => {
    const draft = {
      meta: { layout: { "node-1": { x: 0, y: 0 } } },
      pipeline: { nodes: [{ id: "node-1", agent: "gaia", prompt: "", depends_on: [] }] },
    };
    const statusByNode = { "node-1": "running" };

    const nodes = toFlowNodes(draft as { meta: { layout: Record<string, { x: number; y: number }> }; pipeline: { nodes: { id: string; agent: string; prompt: string; depends_on: string[] }[] } }, null, statusByNode);
    
    expect(nodes[0].data.status).toBe("running");
  });
});

describe("toFlowEdges", () => {
  it("creates edges from depends_on relationships", () => {
    const pipeline = makePipeline({
      nodes: [
        { id: "a", agent: "gaia", prompt: "", depends_on: [] },
        { id: "b", agent: "gaia", prompt: "", depends_on: ["a"] },
        { id: "c", agent: "gaia", prompt: "", depends_on: ["a", "b"] },
      ],
    });

    const edges = toFlowEdges(pipeline);
    
    expect(edges).toHaveLength(3);
    expect(edges.find((e) => e.id === "a->b")).toBeDefined();
    expect(edges.find((e) => e.id === "a->c")).toBeDefined();
    expect(edges.find((e) => e.id === "b->c")).toBeDefined();
  });

  it("creates edges with correct source and target", () => {
    const pipeline = makePipeline({
      nodes: [
        { id: "plan", agent: "gaia", prompt: "", depends_on: [] },
        { id: "impl", agent: "gaia", prompt: "", depends_on: ["plan"] },
      ],
    });

    const edges = toFlowEdges(pipeline);
    
    expect(edges[0].source).toBe("plan");
    expect(edges[0].target).toBe("impl");
    expect(edges[0].type).toBe("smoothstep");
  });
});

describe("applyConnection", () => {
  it("adds dependency when connecting nodes", () => {
    const pipeline = makePipeline({
      nodes: [
        { id: "a", agent: "gaia", prompt: "", depends_on: [] },
        { id: "b", agent: "gaia", prompt: "", depends_on: [] },
      ],
    });

    applyConnection(pipeline, { source: "a", target: "b" });
    
    expect(pipeline.nodes[1].depends_on).toContain("a");
  });

  it("does not duplicate dependencies", () => {
    const pipeline = makePipeline({
      nodes: [
        { id: "a", agent: "gaia", prompt: "", depends_on: [] },
        { id: "b", agent: "gaia", prompt: "", depends_on: ["a"] },
      ],
    });

    applyConnection(pipeline, { source: "a", target: "b" });
    
    expect(pipeline.nodes[1].depends_on).toEqual(["a"]);
  });

  it("ignores invalid connections", () => {
    const pipeline = makePipeline({
      nodes: [{ id: "a", agent: "gaia", prompt: "", depends_on: [] }],
    });

    // Missing source
    applyConnection(pipeline, { source: null, target: "a" });
    expect(pipeline.nodes[0].depends_on).toEqual([]);

    // Missing target
    applyConnection(pipeline, { source: "a", target: null });
    expect(pipeline.nodes[0].depends_on).toEqual([]);

    // Self-connection
    applyConnection(pipeline, { source: "a", target: "a" });
    expect(pipeline.nodes[0].depends_on).toEqual([]);

    // Non-existent target
    applyConnection(pipeline, { source: "a", target: "nonexistent" });
    expect(pipeline.nodes[0].depends_on).toEqual([]);
  });
});

describe("removeConnection", () => {
  it("removes dependency from the target node", () => {
    const pipeline = makePipeline({
      nodes: [
        { id: "a", agent: "gaia", prompt: "", depends_on: [] },
        { id: "b", agent: "gaia", prompt: "", depends_on: ["a"] },
      ],
    });
    const edge: Edge = { id: "a->b", source: "a", target: "b" };

    removeConnection(pipeline, edge);
    
    expect(pipeline.nodes[1].depends_on).toEqual([]);
  });

  it("does nothing if target node does not exist", () => {
    const pipeline = makePipeline({
      nodes: [{ id: "a", agent: "gaia", prompt: "", depends_on: [] }],
    });
    const edge: Edge = { id: "a->nonexistent", source: "a", target: "nonexistent" };

    removeConnection(pipeline, edge);
    
    expect(pipeline.nodes[0].depends_on).toEqual([]);
  });
});

describe("renameNode", () => {
  it("renames a node and updates all references", () => {
    const pipeline = makePipeline({
      nodes: [
        { id: "a", agent: "gaia", prompt: "", depends_on: [] },
        { id: "b", agent: "gaia", prompt: "", depends_on: ["a"] },
        { id: "c", agent: "gaia", prompt: "", depends_on: ["a", "b"] },
      ],
    });
    const layout = { a: { x: 100, y: 100 } };

    renameNode(pipeline, layout, "a", "plan");
    
    expect(pipeline.nodes[0].id).toBe("plan");
    expect(pipeline.nodes[1].depends_on).toEqual(["plan"]);
    expect(pipeline.nodes[2].depends_on).toEqual(["plan", "b"]);
    expect(layout["plan"]).toEqual({ x: 100, y: 100 });
    expect(layout["a"]).toBeUndefined();
  });

  it("does nothing when old and new IDs are the same", () => {
    const pipeline = makePipeline({
      nodes: [{ id: "a", agent: "gaia", prompt: "", depends_on: [] }],
    });
    const originalPipeline = JSON.parse(JSON.stringify(pipeline));
    const layout = {};

    renameNode(pipeline, layout, "a", "a");
    
    expect(pipeline).toEqual(originalPipeline);
  });
});

describe("normalizeNode", () => {
  it("normalizes a raw node object", () => {
    const raw = {
      id: "test-node",
      agent: "gaia",
      prompt: "Hello",
      depends_on: ["a", "b"],
    };

    const result = normalizeNode(raw);
    
    expect(result.id).toBe("test-node");
    expect(result.agent).toBe("gaia");
    expect(result.prompt).toBe("Hello");
    expect(result.depends_on).toEqual(["a", "b"]);
  });

  it("provides default values for missing fields", () => {
    const raw = { id: null, agent: undefined };

    const result = normalizeNode(raw);
    
    expect(result.id).toBe("");
    expect(result.agent).toBe("gaia");
    expect(result.prompt).toBe("");
    expect(result.depends_on).toEqual([]);
  });

  it("preserves extra fields", () => {
    const raw = {
      id: "node-1",
      agent: "gaia",
      prompt: "",
      depends_on: [],
      extra_field: "preserved",
      nested: { value: 123 },
    };

    const result = normalizeNode(raw);
    
    expect((result as Record<string, unknown>).extra_field).toBe("preserved");
    expect((result as Record<string, unknown>).nested).toEqual({ value: 123 });
  });

  it("converts non-string depends_on values", () => {
    const raw = {
      id: "test",
      agent: "gaia",
      depends_on: [1, 2, 3] as unknown as string[],
    };

    const result = normalizeNode(raw);
    
    expect(result.depends_on).toEqual(["1", "2", "3"]);
  });
});
