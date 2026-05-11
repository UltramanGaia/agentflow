import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { useToasts } from "../../app/providers";
import { FilterBar } from "../../components/controls/FilterBar";
import { SearchInput } from "../../components/controls/SearchInput";
import { SegmentedControl } from "../../components/controls/SegmentedControl";
import { EmptyState, ErrorState, LoadingState } from "../../components/feedback/States";
import { PageHeader } from "../../components/layout/PageHeader";
import { PageSection } from "../../components/layout/PageSection";
import { StatusBadge } from "../../components/status/StatusBadge";
import { StatusSummary } from "../../components/status/StatusSummary";
import { defaultGraph } from "../../features/graph-editor/mappers";
import { createGraph, listGraphs } from "../../features/graphs/api";
import { listRuns } from "../../features/runs/api";
import type { RunSummary } from "../../types/api";

type RunFilter = "all" | "running" | "failed" | "attention";
type RunSort = "recent" | "status" | "name";

function formatDate(value?: string | null) {
  if (!value) {
    return "n/a";
  }
  return new Date(value).toLocaleString();
}

function getFailureCount(run: RunSummary) {
  return run.failed_nodes.length;
}

function getActivityTime(run: RunSummary) {
  return run.finished_at ?? run.started_at ?? run.created_at;
}

export function RunsPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const queryClient = useQueryClient();
  const { pushToast } = useToasts();
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<RunFilter>("all");
  const [sort, setSort] = useState<RunSort>("recent");
  const [autoRefresh, setAutoRefresh] = useState(false);

  const runsQuery = useQuery({
    queryKey: ["runs"],
    queryFn: listRuns,
    refetchInterval: autoRefresh ? 15_000 : false,
  });
  const graphsQuery = useQuery({ queryKey: ["graphs"], queryFn: listGraphs });
  const createGraphMutation = useMutation({
    mutationFn: () => {
      const graph = defaultGraph();
      return createGraph({ pipeline: graph.pipeline, layout: graph.meta.layout });
    },
    onSuccess: async (graph) => {
      await queryClient.invalidateQueries({ queryKey: ["graphs"] });
      pushToast({
        tone: "success",
        title: "Graph created",
        description: `${graph.pipeline.name} is ready for editing.`,
      });
      navigate(`/graphs/${graph.meta.id}/edit`);
    },
    onError: (error: Error) => {
      pushToast({ tone: "danger", title: "Graph creation failed", description: error.message });
    },
  });

  const runs = runsQuery.data ?? [];
  const graphs = graphsQuery.data ?? [];
  const searchNeedle = search.trim().toLowerCase();
  const filteredRuns = useMemo(() => {
    return runs
      .filter((run) => {
        if (statusFilter === "running") {
          return run.status === "running";
        }
        if (statusFilter === "failed") {
          return getFailureCount(run) > 0 || run.status === "failed";
        }
        if (statusFilter === "attention") {
          return run.status === "running" || getFailureCount(run) > 0;
        }
        return true;
      })
      .filter((run) => {
        if (!searchNeedle) {
          return true;
        }
        return (
          run.pipeline_name.toLowerCase().includes(searchNeedle) ||
          run.id.toLowerCase().includes(searchNeedle) ||
          run.failed_nodes.some((nodeId) => nodeId.toLowerCase().includes(searchNeedle))
        );
      })
      .sort((left, right) => {
        if (sort === "name") {
          return left.pipeline_name.localeCompare(right.pipeline_name);
        }
        if (sort === "status") {
          return `${left.status}-${left.id}`.localeCompare(`${right.status}-${right.id}`);
        }
        return new Date(getActivityTime(right)).getTime() - new Date(getActivityTime(left)).getTime();
      });
  }, [runs, searchNeedle, sort, statusFilter]);

  const running = runs.filter((run) => run.status === "running").length;
  const failed = runs.filter((run) => getFailureCount(run) > 0 || run.status === "failed").length;
  const activeRuns = filteredRuns.filter((run) => run.status === "running");
  const failedRuns = filteredRuns.filter((run) => getFailureCount(run) > 0 || run.status === "failed");
  const latestCompleted = [...runs]
    .filter((run) => run.status === "completed")
    .sort((left, right) => new Date(getActivityTime(right)).getTime() - new Date(getActivityTime(left)).getTime())[0];
  const focusGraphs = location.pathname === "/graphs";

  if (runsQuery.isLoading || graphsQuery.isLoading) {
    return <LoadingState>Loading runs and graphs...</LoadingState>;
  }
  if (runsQuery.error) {
    return <ErrorState message={runsQuery.error.message} />;
  }
  if (graphsQuery.error) {
    return <ErrorState message={graphsQuery.error.message} />;
  }

  return (
    <div className="page-stack">
      <PageHeader
        eyebrow={focusGraphs ? "Authoring" : "Operations"}
        title={focusGraphs ? "Graphs" : "Runs"}
        description={
          focusGraphs
            ? "Jump into a saved graph, create a new draft, or inspect recent pipeline changes."
            : "Triage failures, watch active runs, and move from landing page to diagnostics without digging through raw runtime state."
        }
        actions={
          <>
            <button
              className="button"
              onClick={() => {
                void runsQuery.refetch();
                void graphsQuery.refetch();
              }}
              type="button"
            >
              Refresh
            </button>
            <button className="button primary" onClick={() => createGraphMutation.mutate()} type="button">
              New Graph
            </button>
          </>
        }
      />

      <div className="summary-grid">
        <StatusSummary hint="All recorded runs" label="Total runs" value={runs.length} />
        <StatusSummary hint="Currently executing" label="Running" status={running > 0 ? "running" : undefined} value={running} />
        <StatusSummary hint="Needs attention now" label="Failed" status={failed > 0 ? "failed" : undefined} value={failed} />
        <StatusSummary
          hint={latestCompleted ? formatDate(latestCompleted.finished_at) : "No completed runs yet"}
          label="Last completed"
          value={latestCompleted?.pipeline_name ?? "None"}
        />
      </div>

      {!focusGraphs ? (
        <FilterBar>
          <SearchInput
            placeholder="Find by run id, pipeline, or failed node"
            value={search}
            onChange={setSearch}
          />
          <div className="field">
            <span className="field-label">Scope</span>
            <SegmentedControl
              options={[
                { label: "All", value: "all" },
                { label: "Running", value: "running" },
                { label: "Failed", value: "failed" },
                { label: "Needs Attention", value: "attention" },
              ]}
              value={statusFilter}
              onChange={setStatusFilter}
            />
          </div>
          <label className="field">
            <span className="field-label">Sort</span>
            <select value={sort} onChange={(event) => setSort(event.target.value as RunSort)}>
              <option value="recent">Most recent activity</option>
              <option value="status">Status</option>
              <option value="name">Pipeline name</option>
            </select>
          </label>
          <label className="checkbox-item">
            <input checked={autoRefresh} onChange={(event) => setAutoRefresh(event.target.checked)} type="checkbox" />
            Auto-refresh
          </label>
        </FilterBar>
      ) : null}

      <div className="layout">
        <div className="detail-stack">
          {!focusGraphs ? (
            <>
              <PageSection
                title="Recent failures"
                description="Failure-first view for runs that already need intervention."
              >
                {failedRuns.length ? (
                  <div className="list">
                    {failedRuns.map((run) => (
                      <RunCard key={run.id} run={run} />
                    ))}
                  </div>
                ) : (
                  <EmptyState title="No failed runs" description="Recent executions are clean." />
                )}
              </PageSection>

              <PageSection
                title="Active runs"
                description="Keep an eye on inflight work without scanning the full history."
              >
                {activeRuns.length ? (
                  <div className="list">
                    {activeRuns.map((run) => (
                      <RunCard key={run.id} run={run} />
                    ))}
                  </div>
                ) : (
                  <EmptyState title="No active runs" description="Nothing is executing right now." />
                )}
              </PageSection>

              <PageSection
                title="All runs"
                description="Filtered execution history with quick links into runtime detail."
              >
                {filteredRuns.length ? (
                  <div className="list">
                    {filteredRuns.map((run) => (
                      <RunCard key={run.id} run={run} />
                    ))}
                  </div>
                ) : (
                  <EmptyState
                    title="No runs yet"
                    description="Create or start a graph to populate runtime history."
                  />
                )}
              </PageSection>
            </>
          ) : (
            <PageSection
              title="Saved graphs"
              description="Your latest pipeline definitions, sorted by update time."
            >
              {graphs.length ? (
                <div className="list">
                  {graphs.map((graph) => (
                    <div className="list-item" key={graph.id}>
                      <div className="list-row-head">
                        <Link className="list-title" to={`/graphs/${graph.id}/edit`}>
                          {graph.name}
                        </Link>
                        <span className="status-badge status-completed">ready</span>
                      </div>
                      <div className="run-card-meta">
                        <span>{graph.node_count} nodes</span>
                        <span>Updated {formatDate(graph.updated_at)}</span>
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <EmptyState title="No graphs saved" description="Create a graph to start editing and running pipelines." />
              )}
            </PageSection>
          )}
        </div>

        <div className="sidebar-list">
          <PageSection title="Graphs" description="Recent graphs and quick authoring jumps.">
            {graphs.length ? (
              <div className="list">
                {graphs.slice(0, 6).map((graph) => (
                  <div className="list-item" key={graph.id}>
                    <Link className="list-title" to={`/graphs/${graph.id}/edit`}>
                      {graph.name}
                    </Link>
                    <div className="run-card-meta">
                      <span>{graph.node_count} nodes</span>
                      <span>{formatDate(graph.updated_at)}</span>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <EmptyState title="No graphs saved" description="Create a graph to start editing and running pipelines." />
            )}
          </PageSection>

          <PageSection title="Quick actions" description="Start a new graph or move directly into authoring.">
            <button className="button primary" onClick={() => createGraphMutation.mutate()} type="button">
              Create Graph
            </button>
            <Link className="button" to="/graphs">
              Open graph workspace
            </Link>
            {failedRuns[0] ? (
              <Link className="button" to={`/runs/${failedRuns[0].id}`}>
                Open latest failing run
              </Link>
            ) : null}
          </PageSection>
        </div>
      </div>
    </div>
  );
}

function RunCard({ run }: { run: RunSummary }) {
  const failedNodes = getFailureCount(run) ? run.failed_nodes.join(", ") : "No failed nodes";

  return (
    <Link className="run-card" to={`/runs/${run.id}`}>
      <div className="list-row-head">
        <div>
          <div className="run-card-title">{run.pipeline_name}</div>
          <div className="muted">{run.id}</div>
        </div>
        <StatusBadge status={run.status} />
      </div>
      <div className="run-card-meta">
        <span>Started {formatDate(run.started_at ?? run.created_at)}</span>
        <span>Finished {formatDate(run.finished_at)}</span>
        <span>{run.node_count} nodes</span>
      </div>
      <div className="run-card-meta">
        <span>{getFailureCount(run)} failed</span>
        <span>{`failed: ${failedNodes}`}</span>
      </div>
    </Link>
  );
}
