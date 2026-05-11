import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { RunsPage } from "./runs/RunsPage";

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return function Wrapper({ children }: { children: React.ReactNode }) {
    return (
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>{children}</MemoryRouter>
      </QueryClientProvider>
    );
  };
}

const mockRuns = [
  {
    id: "run-1",
    status: "completed",
    created_at: "2024-01-01T00:00:00Z",
    started_at: "2024-01-01T00:01:00Z",
    finished_at: "2024-01-01T00:05:00Z",
    pipeline_name: "test-pipeline",
    node_count: 3,
    failed_nodes: [],
  },
  {
    id: "run-2",
    status: "failed",
    created_at: "2024-01-01T01:00:00Z",
    started_at: "2024-01-01T01:01:00Z",
    finished_at: "2024-01-01T01:02:00Z",
    pipeline_name: "failing-pipeline",
    node_count: 2,
    failed_nodes: ["apply"],
  },
];

const mockGraphs = [
  {
    id: "graph-1",
    name: "My Graph",
    updated_at: "2024-01-01T00:00:00Z",
    node_count: 3,
  },
];

describe("RunsPage", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  function mockFetch(responses: Record<string, unknown>) {
    vi.mocked(fetch).mockImplementation(async (input) => {
      const url = typeof input === "string" ? input : input.toString();
      for (const [path, data] of Object.entries(responses)) {
        if (url === path) {
          return {
            ok: true,
            json: () => Promise.resolve(data),
          } as Response;
        }
      }
      return {
        ok: true,
        json: () => Promise.resolve([]),
      } as Response;
    });
  }

  it("renders runs and graphs from API", async () => {
    mockFetch({
      "/api/runs": mockRuns,
      "/api/graphs": mockGraphs,
    });

    render(<RunsPage />, { wrapper: createWrapper() });

    await waitFor(() => {
      expect(screen.getAllByText("test-pipeline").length).toBeGreaterThan(0);
    });
    await waitFor(() => {
      expect(screen.getByText("My Graph")).toBeInTheDocument();
    });
  });

  it("shows summary cards with correct counts", async () => {
    mockFetch({
      "/api/runs": mockRuns,
      "/api/graphs": mockGraphs,
    });

    render(<RunsPage />, { wrapper: createWrapper() });

    await waitFor(() => {
      const totalRunsCard = screen.getByText("Total runs").closest(".metric-card");
      expect(totalRunsCard).not.toBeNull();
      expect(within(totalRunsCard!).getByText("2")).toBeInTheDocument();
    });
  });

  it("shows failed node information", async () => {
    mockFetch({
      "/api/runs": mockRuns,
      "/api/graphs": mockGraphs,
    });

    render(<RunsPage />, { wrapper: createWrapper() });

    await waitFor(() => {
      expect(screen.getAllByText(/failed: apply/).length).toBeGreaterThan(0);
    });
  });

  it("shows empty states when no data", async () => {
    mockFetch({
      "/api/runs": [],
      "/api/graphs": [],
    });

    render(<RunsPage />, { wrapper: createWrapper() });

    await waitFor(() => {
      expect(screen.getByText("No runs yet")).toBeInTheDocument();
    });
    await waitFor(() => {
      expect(screen.getByText("No graphs saved")).toBeInTheDocument();
    });
  });

  it("shows error state when API fails", async () => {
    vi.mocked(fetch).mockResolvedValueOnce({
      ok: false,
      status: 500,
      json: () => Promise.resolve({ detail: "Server error" }),
    } as Response);

    // Graphs request needs to succeed or fail too
    vi.mocked(fetch).mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve([]),
    } as Response);

    render(<RunsPage />, { wrapper: createWrapper() });

    await waitFor(() => {
      expect(screen.getByText("Server error")).toBeInTheDocument();
    });
  });
});
