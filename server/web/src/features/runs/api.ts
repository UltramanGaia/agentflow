import { requestJson } from "../../lib/http";
import { runDetailSchema, runSummarySchema, type RunDetail, type RunSummary } from "../../types/api";

export async function listRuns(): Promise<RunSummary[]> {
  const data = await requestJson<unknown[]>("/api/runs");
  return runSummarySchema.array().parse(data);
}

export async function getRunDetail(runId: string): Promise<RunDetail> {
  const data = await requestJson<unknown>(`/api/runs/${runId}`);
  return runDetailSchema.parse(data);
}

export async function cancelRun(runId: string) {
  return requestJson<{ run: { id: string }; redirected_run_id?: string }>(`/api/runs/${runId}/cancel`, {
    method: "POST",
    body: "{}",
  });
}

export async function resumeRun(runId: string) {
  return requestJson<{ run: { id: string }; redirected_run_id?: string }>(`/api/runs/${runId}/resume`, {
    method: "POST",
    body: "{}",
  });
}

export async function rerunRun(runId: string) {
  return requestJson<{ run: { id: string }; redirected_run_id?: string }>(`/api/runs/${runId}/rerun`, {
    method: "POST",
    body: "{}",
  });
}

export async function rerunNode(runId: string, nodeId: string) {
  return requestJson<{ run: { id: string }; redirected_run_id?: string }>(
    `/api/runs/${runId}/rerun-node/${nodeId}`,
    {
      method: "POST",
      body: "{}",
    },
  );
}

export async function createRun(payload: { graph_id?: string; pipeline?: unknown }) {
  return requestJson<{ run: { id: string } }>("/api/runs", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}
