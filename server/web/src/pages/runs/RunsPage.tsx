import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { EmptyState, ErrorState, LoadingState } from "../../components/feedback/States";
import { StatusBadge } from "../../components/status/StatusBadge";
import { getRunDetail, listRuns } from "../../features/runs/api";
import { RunDetailWorkspace } from "../run-detail/RunDetailWorkspace";
import type { RunSummary } from "../../types/api";

function formatDate(value?: string | null) {
  if (!value) {
    return "n/a";
  }
  return new Date(value).toLocaleString();
}

function getActivityTime(run: RunSummary) {
  return run.finished_at ?? run.started_at ?? run.created_at;
}

export function RunsPage() {
  const [autoRefresh, setAutoRefresh] = useState(false);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);

  const runsQuery = useQuery({
    queryKey: ["runs"],
    queryFn: listRuns,
    refetchInterval: autoRefresh ? 15_000 : false,
  });

  const runs = useMemo(
    () =>
      [...(runsQuery.data ?? [])].sort(
        (left, right) => new Date(getActivityTime(right)).getTime() - new Date(getActivityTime(left)).getTime(),
      ),
    [runsQuery.data],
  );

  useEffect(() => {
    if (!runs.length) {
      if (selectedRunId !== null) {
        setSelectedRunId(null);
      }
      return;
    }
    if (!selectedRunId || !runs.some((run) => run.id === selectedRunId)) {
      setSelectedRunId(runs[0].id);
    }
  }, [runs, selectedRunId]);

  const selectedRun = runs.find((run) => run.id === selectedRunId) ?? null;

  const runDetailQuery = useQuery({
    queryKey: ["run-detail", selectedRunId],
    queryFn: () => getRunDetail(selectedRunId!),
    enabled: Boolean(selectedRunId),
    refetchInterval: autoRefresh ? 15_000 : false,
  });

  const isRefreshing = runsQuery.isFetching || runDetailQuery.isFetching;

  if (runsQuery.isLoading) {
    return <LoadingState>Loading runs...</LoadingState>;
  }
  if (runsQuery.error) {
    return <ErrorState message={runsQuery.error.message} />;
  }

  return (
    <div className="runs-page">
      <div className="layout runs-workspace">
        <div className="sidebar-list panel">
          <div className="section-header">
            <div>
              <h2>Runs</h2>
              <p className="section-description">{runs.length ? `${runs.length} run(s), newest first.` : "No runs available."}</p>
            </div>
            <div className="page-actions">
              <label className="checkbox-item">
                <input checked={autoRefresh} onChange={(event) => setAutoRefresh(event.target.checked)} type="checkbox" />
                Auto-refresh
              </label>
              <button
                className="button"
                disabled={isRefreshing}
                onClick={() => {
                  void runsQuery.refetch();
                  void runDetailQuery.refetch();
                }}
                type="button"
              >
                {isRefreshing ? "Refreshing..." : "Refresh"}
              </button>
            </div>
          </div>

          <div className="list">
            {runs.length ? (
              runs.map((run) => (
                <button
                  className={`run-card${run.id === selectedRunId ? " active" : ""}`}
                  key={run.id}
                  onClick={() => setSelectedRunId(run.id)}
                  type="button"
                >
                  <div className="list-row-head">
                    <div>
                      <div className="run-card-title">{run.pipeline_name}</div>
                      <div className="muted">{run.id}</div>
                    </div>
                    <StatusBadge status={run.status} />
                  </div>
                  <div className="run-card-meta">
                    <span>{formatDate(getActivityTime(run))}</span>
                  </div>
                </button>
              ))
            ) : (
              <EmptyState title="No runs yet" description="Run history will appear here after executions are recorded." />
            )}
          </div>
        </div>

        <div className="detail-stack">
          {!selectedRun ? (
            <EmptyState title="No run selected" description="Pick a run from the left sidebar to inspect its graph." />
          ) : runDetailQuery.isLoading ? (
            <LoadingState>Loading run detail...</LoadingState>
          ) : runDetailQuery.error ? (
            <ErrorState message={runDetailQuery.error.message} />
          ) : runDetailQuery.data ? (
            <RunDetailWorkspace
              detail={runDetailQuery.data}
              embedded
              onNavigateRun={setSelectedRunId}
              runId={selectedRun.id}
            />
          ) : (
            <ErrorState message="Run detail not found." />
          )}
        </div>
      </div>
    </div>
  );
}
