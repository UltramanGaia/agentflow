import { z } from "zod";

export const pipelineNodeSchema = z
  .object({
    id: z.string(),
    agent: z.string(),
    prompt: z.string().optional().default(""),
    depends_on: z.array(z.string()).default([]),
  })
  .catchall(z.unknown());

export const pipelineSpecSchema = z
  .object({
    name: z.string(),
    description: z.string().nullable().optional().default(""),
    working_dir: z.string().optional(),
    concurrency: z.number().optional(),
    fail_fast: z.boolean().optional(),
    max_iterations: z.number().optional(),
    scratchboard: z.boolean().optional(),
    use_worktree: z.boolean().optional(),
    nodes: z.array(pipelineNodeSchema),
  })
  .catchall(z.unknown());

export const graphSummarySchema = z.object({
  id: z.string(),
  name: z.string(),
  description: z.string().nullable().optional(),
  updated_at: z.string(),
  node_count: z.number(),
});

export const graphViewSchema = z.object({
  meta: z.object({
    id: z.string(),
    name: z.string(),
    description: z.string().nullable().optional(),
    created_at: z.string(),
    updated_at: z.string(),
    layout: z.record(z.string(), z.object({ x: z.number(), y: z.number() })),
  }),
  pipeline: pipelineSpecSchema,
});

export const runSummarySchema = z.object({
  id: z.string(),
  status: z.string(),
  created_at: z.string(),
  started_at: z.string().nullable().optional(),
  finished_at: z.string().nullable().optional(),
  pipeline_name: z.string(),
  node_count: z.number(),
  failed_nodes: z.array(z.string()).default([]),
});

export const runNodeArtifactSchema = z.object({
  name: z.string(),
  size: z.number(),
});

export const runNodeSchema = z.object({
  id: z.string(),
  agent: z.string(),
  prompt: z.string(),
  depends_on: z.array(z.string()).default([]),
  status: z.string(),
  started_at: z.string().nullable().optional(),
  finished_at: z.string().nullable().optional(),
  exit_code: z.number().nullable().optional(),
  final_response: z.string().nullable().optional(),
  output: z.string().nullable().optional(),
  artifacts: z.array(runNodeArtifactSchema).default([]),
});

export const runDetailSchema = z.object({
  run: z
    .object({
      id: z.string(),
      status: z.string(),
      pipeline: pipelineSpecSchema,
      nodes: z.record(z.string(), z.unknown()),
    })
    .catchall(z.unknown()),
  graph: z.object({
    nodes: z.array(runNodeSchema),
    edges: z.array(
      z.object({
        id: z.string(),
        source: z.string(),
        target: z.string(),
      }),
    ),
  }),
  events: z.array(
    z
      .object({
        type: z.string(),
        timestamp: z.string().optional(),
        node_id: z.string().nullable().optional(),
        data: z.record(z.string(), z.unknown()).optional(),
      })
      .catchall(z.unknown()),
  ),
});

export type PipelineNode = z.infer<typeof pipelineNodeSchema>;
export type PipelineSpec = z.infer<typeof pipelineSpecSchema>;
export type GraphSummary = z.infer<typeof graphSummarySchema>;
export type GraphView = z.infer<typeof graphViewSchema>;
export type RunSummary = z.infer<typeof runSummarySchema>;
export type RunNode = z.infer<typeof runNodeSchema>;
export type RunDetail = z.infer<typeof runDetailSchema>;
