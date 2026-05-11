import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
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

const mockRunDetail = {
  run: {
    id: "run-2",
    status: "failed",
    pipeline: { name: "failing-pipeline", nodes: [] },
    nodes: {},
  },
  graph: { nodes: [], edges: [] },
  events: [],
};

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

  it("renders runs from API", async () => {
    mockFetch({
      "/api/runs": mockRuns,
      "/api/runs/run-2": mockRunDetail,
    });

    render(<RunsPage />, { wrapper: createWrapper() });

    await waitFor(() => {
      expect(screen.getAllByText("test-pipeline").length).toBeGreaterThan(0);
    });
  });

  it("renders newest runs first in the sidebar", async () => {
    mockFetch({
      "/api/runs": mockRuns,
      "/api/runs/run-2": mockRunDetail,
    });

    const { container } = render(<RunsPage />, { wrapper: createWrapper() });

    await waitFor(() => {
      const titles = Array.from(container.querySelectorAll(".sidebar-list .run-card-title")).map((node) => node.textContent);
      expect(titles).toEqual(["failing-pipeline", "test-pipeline"]);
    });
  });

  it("shows selected run graph workspace", async () => {
    mockFetch({
      "/api/runs": mockRuns,
      "/api/runs/run-2": {
        run: { id: "run-2", status: "failed", pipeline: { name: "failing-pipeline", nodes: [] }, nodes: {} },
        graph: {
          nodes: [
            {
              id: "apply",
              agent: "gaia",
              prompt: "",
              depends_on: [],
              status: "failed",
              started_at: null,
              finished_at: null,
              exit_code: 1,
              final_response: null,
              output: null,
              tick_count: 0,
              attempts: [],
              artifacts: [],
            },
          ],
          edges: [],
        },
        events: [],
      },
    });

    render(<RunsPage />, { wrapper: createWrapper() });

    await waitFor(() => {
      expect(screen.getByText("Stage view")).toBeInTheDocument();
      expect(screen.getByText("gaia")).toBeInTheDocument();
      expect(screen.getAllByText("failing-pipeline").length).toBeGreaterThan(0);
    });
  });

  it("shows empty states when no data", async () => {
    mockFetch({
      "/api/runs": [],
    });

    render(<RunsPage />, { wrapper: createWrapper() });

    await waitFor(() => {
      expect(screen.getByText("No runs yet")).toBeInTheDocument();
    });
  });

  it("shows error state when API fails", async () => {
    vi.mocked(fetch).mockResolvedValue({
      ok: false,
      status: 500,
      json: () => Promise.resolve({ detail: "Server error" }),
    } as Response);

    render(<RunsPage />, { wrapper: createWrapper() });

    await waitFor(() => {
      expect(screen.getByText("Server error")).toBeInTheDocument();
    });
  });
});
