import { requestJson } from "../../lib/http";
import {
  graphSummarySchema,
  graphViewSchema,
  pipelineSpecSchema,
  type GraphSummary,
  type GraphView,
  type PipelineSpec,
} from "../../types/api";

export async function listGraphs(): Promise<GraphSummary[]> {
  const data = await requestJson<unknown[]>("/api/graphs");
  return graphSummarySchema.array().parse(data);
}

export async function getGraph(graphId: string): Promise<GraphView> {
  const data = await requestJson<unknown>(`/api/graphs/${graphId}`);
  return graphViewSchema.parse(data);
}

export async function createGraph(payload: { pipeline: PipelineSpec; layout: Record<string, { x: number; y: number }> }) {
  const data = await requestJson<unknown>("/api/graphs", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  return graphViewSchema.parse(data);
}

export async function updateGraph(
  graphId: string,
  payload: { graph_id?: string; pipeline: PipelineSpec; layout: Record<string, { x: number; y: number }> },
) {
  const data = await requestJson<unknown>(`/api/graphs/${graphId}`, {
    method: "PUT",
    body: JSON.stringify(payload),
  });
  return graphViewSchema.parse(data);
}

export async function validateGraph(pipeline: PipelineSpec) {
  return requestJson<{ valid: boolean; pipeline: PipelineSpec }>("/api/graphs/validate", {
    method: "POST",
    body: JSON.stringify({ pipeline }),
  });
}

export async function importGraph(path: string): Promise<PipelineSpec> {
  const data = await requestJson<{ pipeline: unknown }>("/api/graphs/import", {
    method: "POST",
    body: JSON.stringify({ path }),
  });
  return pipelineSpecSchema.parse(data.pipeline);
}

export async function exportGraphPython(graphId: string) {
  return requestJson<{ graph_id: string; filename: string; content: string }>(`/api/graphs/${graphId}/export/python`);
}
