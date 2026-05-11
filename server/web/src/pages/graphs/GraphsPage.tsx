import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";
import { useToasts } from "../../app/providers";
import { EmptyState, ErrorState, LoadingState } from "../../components/feedback/States";
import { PageHeader } from "../../components/layout/PageHeader";
import { PageSection } from "../../components/layout/PageSection";
import { StatusSummary } from "../../components/status/StatusSummary";
import { defaultGraph } from "../../features/graph-editor/mappers";
import { createGraph, listGraphs } from "../../features/graphs/api";
import { listRuns } from "../../features/runs/api";

function formatDate(value?: string | null) {
  if (!value) {
    return "n/a";
  }
  return new Date(value).toLocaleString();
}

export function GraphsPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { pushToast } = useToasts();
  const graphsQuery = useQuery({ queryKey: ["graphs"], queryFn: listGraphs });
  const runsQuery = useQuery({ queryKey: ["runs"], queryFn: listRuns });

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

  if (graphsQuery.isLoading || runsQuery.isLoading) {
    return <LoadingState>Loading graphs...</LoadingState>;
  }
  if (graphsQuery.error) {
    return <ErrorState message={graphsQuery.error.message} />;
  }
  if (runsQuery.error) {
    return <ErrorState message={runsQuery.error.message} />;
  }

  const graphs = graphsQuery.data ?? [];
  const runs = runsQuery.data ?? [];
  const latestGraph = [...graphs].sort((left, right) => new Date(right.updated_at).getTime() - new Date(left.updated_at).getTime())[0];
  const latestFailingRun = [...runs]
    .filter((run) => run.status === "failed" || run.failed_nodes.length > 0)
    .sort((left, right) => new Date((right.finished_at ?? right.started_at ?? right.created_at)).getTime() - new Date((left.finished_at ?? left.started_at ?? left.created_at)).getTime())[0];
  const totalNodes = graphs.reduce((sum, graph) => sum + graph.node_count, 0);

  return (
    <div className="page-stack">
      <PageHeader
        eyebrow="Authoring"
        title="Graphs"
        description="Jump into a saved graph, create a new draft, or inspect recent pipeline changes."
        actions={
          <>
            <button
              className="button"
              onClick={() => {
                void graphsQuery.refetch();
                void runsQuery.refetch();
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
        <StatusSummary hint="Saved pipeline definitions" label="Graphs" value={graphs.length} />
        <StatusSummary hint="Aggregate authoring surface" label="Total nodes" value={totalNodes} />
        <StatusSummary hint={latestGraph ? formatDate(latestGraph.updated_at) : "No saved graph yet"} label="Latest graph" value={latestGraph?.name ?? "None"} />
        <StatusSummary
          hint={latestFailingRun ? latestFailingRun.id : "No recent failures"}
          label="Latest failing run"
          value={latestFailingRun?.pipeline_name ?? "None"}
        />
      </div>

      <div className="layout">
        <div className="detail-stack">
          <PageSection title="Saved graphs" description="Your latest pipeline definitions, sorted by update time.">
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
        </div>

        <div className="sidebar-list">
          <PageSection title="Quick actions" description="Start a new graph or jump back into runtime operations.">
            <button className="button primary" onClick={() => createGraphMutation.mutate()} type="button">
              Create Graph
            </button>
            <Link className="button" to="/graphs/new/edit">
              Open blank editor
            </Link>
            <Link className="button" to="/runs">
              Open runs workspace
            </Link>
            {latestFailingRun ? (
              <Link className="button" to={`/runs/${latestFailingRun.id}`}>
                Open latest failing run
              </Link>
            ) : null}
          </PageSection>

          <PageSection title="Recent runtime pressure" description="Keep authoring connected to operational failures.">
            {latestFailingRun ? (
              <div className="list-item">
                <div className="list-row-head">
                  <strong>{latestFailingRun.pipeline_name}</strong>
                  <span className="status-badge status-failed">failed</span>
                </div>
                <div className="run-card-meta">
                  <span>{latestFailingRun.id}</span>
                  <span>{latestFailingRun.failed_nodes.length} failed nodes</span>
                </div>
              </div>
            ) : (
              <EmptyState title="No failing runs" description="Recent runtime history does not need graph follow-up." />
            )}
          </PageSection>
        </div>
      </div>
    </div>
  );
}
