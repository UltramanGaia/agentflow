import { describe, expect, it } from "vitest";
import {
  graphSummarySchema,
  graphViewSchema,
  pipelineNodeSchema,
  pipelineSpecSchema,
  runDetailSchema,
  runNodeSchema,
  runSummarySchema,
} from "./api";

describe("pipelineNodeSchema", () => {
  it("parses a valid node", () => {
    const node = {
      id: "plan",
      agent: "gaia",
      prompt: "Plan the work",
      depends_on: [],
    };

    const result = pipelineNodeSchema.parse(node);
    
    expect(result.id).toBe("plan");
    expect(result.agent).toBe("gaia");
    expect(result.prompt).toBe("Plan the work");
    expect(result.depends_on).toEqual([]);
  });

  it("provides default values", () => {
    const node = { id: "a", agent: "gaia" };

    const result = pipelineNodeSchema.parse(node);
    
    expect(result.prompt).toBe("");
    expect(result.depends_on).toEqual([]);
  });

  it("preserves extra fields via catchall", () => {
    const node = {
      id: "a",
      agent: "gaia",
      tools: "read_only",
      success_criteria: [{ kind: "output_contains", value: "LGTM" }],
    };

    const result = pipelineNodeSchema.parse(node);
    
    expect((result as Record<string, unknown>).tools).toBe("read_only");
    expect((result as Record<string, unknown>).success_criteria).toEqual([
      { kind: "output_contains", value: "LGTM" },
    ]);
  });
});

describe("pipelineSpecSchema", () => {
  it("parses a valid pipeline", () => {
    const pipeline = {
      name: "test-pipeline",
      nodes: [
        { id: "plan", agent: "gaia", prompt: "", depends_on: [] },
        { id: "impl", agent: "gaia", prompt: "", depends_on: ["plan"] },
      ],
    };

    const result = pipelineSpecSchema.parse(pipeline);
    
    expect(result.name).toBe("test-pipeline");
    expect(result.nodes).toHaveLength(2);
  });

  it("provides default optional fields", () => {
    const pipeline = { name: "minimal", nodes: [] };

    const result = pipelineSpecSchema.parse(pipeline);
    
    expect(result.description).toBe("");
    expect(result.working_dir).toBeUndefined();
    expect(result.concurrency).toBeUndefined();
  });

  it("preserves extra fields via catchall", () => {
    const pipeline = {
      name: "test",
      nodes: [],
      custom_field: "preserved",
    };

    const result = pipelineSpecSchema.parse(pipeline);
    
    expect((result as Record<string, unknown>).custom_field).toBe("preserved");
  });
});

describe("graphSummarySchema", () => {
  it("parses a graph summary", () => {
    const summary = {
      id: "graph-1",
      name: "My Graph",
      updated_at: "2024-01-01T00:00:00Z",
      node_count: 5,
    };

    const result = graphSummarySchema.parse(summary);
    
    expect(result.id).toBe("graph-1");
    expect(result.name).toBe("My Graph");
    expect(result.node_count).toBe(5);
  });
});

describe("graphViewSchema", () => {
  it("parses a full graph view", () => {
    const graph = {
      meta: {
        id: "graph-1",
        name: "My Graph",
        description: "A test graph",
        created_at: "2024-01-01T00:00:00Z",
        updated_at: "2024-01-02T00:00:00Z",
        layout: {
          plan: { x: 100, y: 50 },
        },
      },
      pipeline: {
        name: "My Graph",
        nodes: [{ id: "plan", agent: "gaia", prompt: "", depends_on: [] }],
      },
    };

    const result = graphViewSchema.parse(graph);
    
    expect(result.meta.id).toBe("graph-1");
    expect(result.meta.layout["plan"]).toEqual({ x: 100, y: 50 });
    expect(result.pipeline.nodes).toHaveLength(1);
  });
});

describe("runSummarySchema", () => {
  it("parses a run summary", () => {
    const run = {
      id: "run-1",
      status: "completed",
      created_at: "2024-01-01T00:00:00Z",
      started_at: "2024-01-01T00:01:00Z",
      finished_at: "2024-01-01T00:05:00Z",
      pipeline_name: "test-pipeline",
      node_count: 3,
      failed_nodes: [],
    };

    const result = runSummarySchema.parse(run);
    
    expect(result.id).toBe("run-1");
    expect(result.status).toBe("completed");
    expect(result.pipeline_name).toBe("test-pipeline");
    expect(result.failed_nodes).toEqual([]);
  });

  it("handles failed nodes", () => {
    const run = {
      id: "run-2",
      status: "failed",
      created_at: "2024-01-01T00:00:00Z",
      pipeline_name: "test",
      node_count: 2,
      failed_nodes: ["apply"],
    };

    const result = runSummarySchema.parse(run);
    
    expect(result.failed_nodes).toEqual(["apply"]);
  });
});

describe("runNodeSchema", () => {
  it("parses a run node", () => {
    const node = {
      id: "plan",
      agent: "gaia",
      prompt: "Plan",
      depends_on: [],
      status: "completed",
      started_at: "2024-01-01T00:00:00Z",
      finished_at: "2024-01-01T00:01:00Z",
      exit_code: 0,
      final_response: "Done",
      output: "Output here",
      artifacts: [{ name: "stdout.log", size: 1024 }],
    };

    const result = runNodeSchema.parse(node);
    
    expect(result.id).toBe("plan");
    expect(result.status).toBe("completed");
    expect(result.artifacts).toHaveLength(1);
    expect(result.artifacts[0].name).toBe("stdout.log");
  });
});

describe("runDetailSchema", () => {
  it("parses full run detail", () => {
    const detail = {
      run: {
        id: "run-1",
        status: "completed",
        pipeline: {
          name: "test",
          nodes: [{ id: "plan", agent: "gaia", prompt: "", depends_on: [] }],
        },
        nodes: {
          plan: {
            node_id: "plan",
            status: "completed",
            output: "ok",
          },
        },
      },
      graph: {
        nodes: [
          {
            id: "plan",
            agent: "gaia",
            prompt: "",
            depends_on: [],
            status: "completed",
            artifacts: [],
          },
        ],
        edges: [],
      },
      events: [
        {
          type: "node_completed",
          timestamp: "2024-01-01T00:00:00Z",
          node_id: "plan",
          data: { duration_ms: 1000 },
        },
      ],
    };

    const result = runDetailSchema.parse(detail);
    
    expect(result.run.id).toBe("run-1");
    expect(result.run.status).toBe("completed");
    expect(result.graph.nodes).toHaveLength(1);
    expect(result.events).toHaveLength(1);
  });
});
