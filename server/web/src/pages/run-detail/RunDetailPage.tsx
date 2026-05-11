import { useQuery } from "@tanstack/react-query";
import { useNavigate, useParams } from "react-router-dom";
import { ErrorState, LoadingState } from "../../components/feedback/States";
import { getRunDetail } from "../../features/runs/api";
import { useRunStream } from "../../features/run-viewer/sse";
import { RunDetailWorkspace } from "./RunDetailWorkspace";

export function RunDetailPage() {
  const navigate = useNavigate();
  const { runId } = useParams();
  useRunStream(runId);

  const runQuery = useQuery({
    queryKey: ["run-detail", runId],
    queryFn: () => getRunDetail(runId!),
    enabled: Boolean(runId),
    refetchInterval: 15_000,
  });

  if (runQuery.isLoading) {
    return <LoadingState>Loading run detail...</LoadingState>;
  }
  if (runQuery.error) {
    return <ErrorState message={runQuery.error.message} />;
  }
  if (!runQuery.data || !runId) {
    return <ErrorState message="Run detail not found." />;
  }

  return <RunDetailWorkspace detail={runQuery.data} onNavigateRun={(nextRunId) => navigate(`/runs/${nextRunId}`)} runId={runId} />;
}
