import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";
import { EmptyState, ErrorState, LoadingState } from "../../components/feedback/States";
import { StatusBadge } from "../../components/status/StatusBadge";
import { defaultGraph } from "../../features/graph-editor/mappers";
import { createGraph, listGraphs } from "../../features/graphs/api";
import { listRuns } from "../../features/runs/api";

export function RunsPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const runsQuery = useQuery({ queryKey: ["runs"], queryFn: listRuns });
  const graphsQuery = useQuery({ queryKey: ["graphs"], queryFn: listGraphs });
  const createGraphMutation = useMutation({
    mutationFn: () => {
      const graph = defaultGraph();
      return createGraph({ pipeline: graph.pipeline, layout: graph.meta.layout });
    },
    onSuccess: async (graph) => {
      await queryClient.invalidateQueries({ queryKey: ["graphs"] });
      navigate(`/graphs/${graph.meta.id}/edit`);
    },
  });

  if (runsQuery.isLoading || graphsQuery.isLoading) {
    return <LoadingState>Loading runs and graphs...</LoadingState>;
  }
  if (runsQuery.error) {
    return <ErrorState message={runsQuery.error.message} />;
  }
  if (graphsQuery.error) {
    return <ErrorState message={graphsQuery.error.message} />;
  }

  const runs = runsQuery.data ?? [];
  const graphs = graphsQuery.data ?? [];
  const running = runs.filter((run) => run.status === "running").length;
  const failed = runs.filter((run) => run.failed_nodes.length > 0).length;

  return (
    <div className="page-stack">
      <section className="summary-grid">
        <div className="panel summary-card">
          <span className="summary-label">Runs</span>
          <strong>{runs.length}</strong>
        </div>
        <div className="panel summary-card">
          <span className="summary-label">Running</span>
          <strong>{running}</strong>
        </div>
        <div className="panel summary-card">
          <span className="summary-label">Failed</span>
          <strong>{failed}</strong>
        </div>
      </section>
      <section className="layout">
        <div className="panel">
          <div className="section-head">
            <div>
              <h2>Runs</h2>
              <p className="muted">Recent execution history and failure hotspots.</p>
            </div>
          </div>
          <div className="list">
            {runs.length ? (
              runs.map((run) => (
                <div className="list-item" key={run.id}>
                  <Link className="list-title" to={`/runs/${run.id}`}>
                    {run.pipeline_name}
                  </Link>
                  <div className="muted">{run.id}</div>
                  <div className="row-wrap">
                    <StatusBadge status={run.status} />
                    <span className="muted">{run.node_count} nodes</span>
                    <span className="muted">
                      {run.failed_nodes.length ? `failed: ${run.failed_nodes.join(", ")}` : "no failed nodes"}
                    </span>
                  </div>
                </div>
              ))
            ) : (
              <EmptyState title="No runs yet" description="Create or start a graph to populate runtime history." />
            )}
          </div>
        </div>
        <div className="panel">
          <div className="section-head">
            <div>
              <h2>Graphs</h2>
              <p className="muted">Jump into a saved pipeline or start a new one.</p>
            </div>
            <button className="button primary" onClick={() => createGraphMutation.mutate()} type="button">
              Create Graph
            </button>
          </div>
          <div className="list">
            {graphs.length ? (
              graphs.map((graph) => (
                <div className="list-item" key={graph.id}>
                  <Link className="list-title" to={`/graphs/${graph.id}/edit`}>
                    {graph.name}
                  </Link>
                  <div className="muted">{graph.updated_at}</div>
                  <div className="muted">{graph.node_count} nodes</div>
                </div>
              ))
            ) : (
              <EmptyState title="No graphs saved" description="Create a graph to start editing and running pipelines." />
            )}
          </div>
        </div>
      </section>
    </div>
  );
}
