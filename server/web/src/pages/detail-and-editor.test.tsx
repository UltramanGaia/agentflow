import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { GraphEditorPage } from "./graph-editor/GraphEditorPage";
import { RunDetailPage } from "./run-detail/RunDetailPage";

const fitViewMock = vi.fn();

vi.mock("@monaco-editor/react", () => ({
  default: ({
    value,
    onChange,
  }: {
    value?: string;
    onChange?: (value: string) => void;
  }) => <textarea data-testid="monaco-editor" value={value ?? ""} onChange={(event) => onChange?.(event.target.value)} />,
}));

vi.mock("reactflow", async () => {
  const React = await import("react");
  return {
    __esModule: true,
    default: ({
      nodes = [],
      onNodeClick,
      children,
    }: {
      nodes?: Array<{ id: string; data?: { title?: string; agent?: string; status?: string; onInspect?: () => void } }>;
      onNodeClick?: (event: unknown, node: { id: string }) => void;
      children?: ReactNode;
    }) => (
      <div data-testid="reactflow">
        {nodes.map((node) => (
          <div key={node.id}>
            <button onClick={() => onNodeClick?.({}, { id: node.id })} type="button">
              {node.data?.title ?? node.id}
            </button>
            <button aria-label={`Inspect ${node.data?.title ?? node.id}`} onClick={() => node.data?.onInspect?.()} type="button">
              Details
            </button>
          </div>
        ))}
        {children}
      </div>
    ),
    ReactFlowProvider: ({ children }: { children: ReactNode }) => <>{children}</>,
    useReactFlow: () => ({ fitView: fitViewMock }),
    Background: () => <div data-testid="rf-background" />,
    Controls: () => <div data-testid="rf-controls" />,
    MiniMap: () => <div data-testid="rf-minimap" />,
    Handle: () => <span data-testid="rf-handle" />,
    MarkerType: { ArrowClosed: "arrowclosed" },
    Position: { Left: "left", Right: "right" },
  };
});

class MockEventSource {
  addEventListener = vi.fn();
  close = vi.fn();
  onerror: (() => void) | null = null;

  constructor(public url: string) {}
}

function createWrapper(initialEntry: string, routePath: string) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });

  return function Wrapper({ children }: { children: React.ReactNode }) {
    return (
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={[initialEntry]}>
          <Routes>
            <Route element={children} path={routePath} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>
    );
  };
}

function jsonResponse(data: unknown): Response {
  return {
    ok: true,
    json: () => Promise.resolve(data),
    text: () => Promise.resolve(JSON.stringify(data)),
  } as Response;
}

function textResponse(text: string): Response {
  return {
    ok: true,
    json: () => Promise.resolve({}),
    text: () => Promise.resolve(text),
  } as Response;
}

const runDetailPayload = {
  run: {
    id: "run-123",
    status: "running",
    pipeline: {
      name: "Deploy pipeline",
      description: "release",
      nodes: [
        { id: "plan", agent: "codex", prompt: "", depends_on: [] },
        { id: "apply", agent: "claude", prompt: "", depends_on: ["plan"] },
      ],
    },
    nodes: {},
  },
  graph: {
    nodes: [
      {
        id: "plan",
        agent: "codex",
        prompt: "",
        depends_on: [],
        status: "completed",
        tick_count: 0,
        attempts: [{ number: 1, status: "completed", exit_code: 0, success_details: [] }],
        artifacts: [{ name: "stdout.log", size: 10 }],
      },
      {
        id: "apply",
        agent: "claude",
        prompt: "",
        depends_on: ["plan"],
        status: "failed",
        tick_count: 2,
        attempts: [{ number: 1, status: "failed", exit_code: 1, success_details: [] }],
        artifacts: [{ name: "stderr.log", size: 24 }],
      },
    ],
    edges: [{ id: "plan->apply", source: "plan", target: "apply" }],
  },
  events: [
    {
      type: "node.failed",
      timestamp: "2024-01-01T00:03:00Z",
      node_id: "apply",
      data: { reason: "boom" },
    },
    {
      type: "node.started",
      timestamp: "2024-01-01T00:02:00Z",
      node_id: "apply",
      data: {},
    },
  ],
};

const graphPayload = {
  meta: {
    id: "graph-123",
    name: "Release graph",
    description: "Deploy flow",
    created_at: "2024-01-01T00:00:00Z",
    updated_at: "2024-01-01T00:00:00Z",
    layout: {
      plan: { x: 0, y: 0 },
      apply: { x: 100, y: 100 },
    },
  },
  pipeline: {
    name: "Release graph",
    description: "Deploy flow",
    working_dir: ".",
    concurrency: 4,
    fail_fast: false,
    max_iterations: 10,
    scratchboard: false,
    use_worktree: false,
    nodes: [
      { id: "plan", agent: "codex", prompt: "Plan it", depends_on: [] },
      { id: "apply", agent: "claude", prompt: "Apply it", depends_on: ["plan"] },
    ],
  },
};

describe("RunDetailPage", () => {
  beforeEach(() => {
    fitViewMock.mockReset();
    vi.stubGlobal("fetch", vi.fn());
    vi.stubGlobal("EventSource", MockEventSource);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("defaults to the failed node and loads its log artifact", async () => {
    const user = userEvent.setup();
    vi.mocked(fetch).mockImplementation(async (input) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url === "/api/runs/run-123") {
        return jsonResponse(runDetailPayload);
      }
      if (url === "/api/runs/run-123/nodes/apply/artifacts/stderr.log") {
        return textResponse("traceback line");
      }
      return jsonResponse({});
    });

    render(<RunDetailPage />, {
      wrapper: createWrapper("/runs/run-123", "/runs/:runId"),
    });

    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "Deploy pipeline" })).toBeInTheDocument();
    });

    expect(screen.getAllByText("apply").length).toBeGreaterThan(0);
    await user.click(screen.getByRole("button", { name: "Inspect apply" }));
    await waitFor(() => {
      expect(screen.getByText("traceback line")).toBeInTheDocument();
    });
    expect(screen.getByRole("button", { name: "Cancel" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Resume" })).toBeDisabled();
  });

  it("shows scoped events for the selected node", async () => {
    const user = userEvent.setup();
    vi.mocked(fetch).mockImplementation(async (input) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url === "/api/runs/run-123") {
        return jsonResponse(runDetailPayload);
      }
      if (url.includes("/stderr.log")) {
        return textResponse("traceback line");
      }
      return jsonResponse({});
    });

    render(<RunDetailPage />, {
      wrapper: createWrapper("/runs/run-123", "/runs/:runId"),
    });

    await waitFor(() => expect(screen.getByRole("heading", { name: "Deploy pipeline" })).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: "Inspect apply" }));
    await waitFor(() => expect(screen.getByText("traceback line")).toBeInTheDocument());
    await user.click(screen.getAllByRole("button", { name: "Events" })[0]!);

    await waitFor(() => {
      expect(screen.getAllByText("node.failed").length).toBeGreaterThan(0);
    });
    expect(screen.getAllByText(/apply/).length).toBeGreaterThan(0);
  });

  it("opens a node dialog from the node detail button", async () => {
    const user = userEvent.setup();
    vi.mocked(fetch).mockImplementation(async (input) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url === "/api/runs/run-123") {
        return jsonResponse(runDetailPayload);
      }
      if (url === "/api/runs/run-123/nodes/apply/artifacts/stderr.log") {
        return textResponse("traceback line");
      }
      return jsonResponse({});
    });

    render(<RunDetailPage />, {
      wrapper: createWrapper("/runs/run-123", "/runs/:runId"),
    });

    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "Deploy pipeline" })).toBeInTheDocument();
    });

    await user.click(screen.getByRole("button", { name: "Inspect apply" }));

    await waitFor(() => {
      expect(screen.getByRole("dialog")).toBeInTheDocument();
    });
    expect(screen.getByText("apply diagnostics")).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByText("traceback line")).toBeInTheDocument();
    });
  });

  it("previews artifacts inline instead of opening a new page", async () => {
    const user = userEvent.setup();
    vi.mocked(fetch).mockImplementation(async (input) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url === "/api/runs/run-123") {
        return jsonResponse(runDetailPayload);
      }
      if (url === "/api/runs/run-123/nodes/apply/artifacts/stderr.log") {
        return textResponse("traceback line");
      }
      return jsonResponse({});
    });

    render(<RunDetailPage />, {
      wrapper: createWrapper("/runs/run-123", "/runs/:runId"),
    });

    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "Deploy pipeline" })).toBeInTheDocument();
    });

    await user.click(screen.getByRole("button", { name: "Inspect apply" }));
    await user.click(screen.getAllByRole("button", { name: "Artifacts" })[0]!);

    await waitFor(() => {
      expect(screen.getByText("Previewing stderr.log")).toBeInTheDocument();
    });
    expect(screen.getByText("traceback line")).toBeInTheDocument();
    expect(screen.getByText("Preview")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Download" })).toBeInTheDocument();
  });
});

describe("GraphEditorPage", () => {
  beforeEach(() => {
    fitViewMock.mockReset();
    vi.stubGlobal("fetch", vi.fn());
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders structured graph and node inspector from API data", async () => {
    vi.mocked(fetch).mockImplementation(async (input) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url === "/api/graphs/graph-123") {
        return jsonResponse(graphPayload);
      }
      return jsonResponse({});
    });

    render(<GraphEditorPage />, {
      wrapper: createWrapper("/graphs/graph-123/edit", "/graphs/:graphId/edit"),
    });

    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "Release graph" })).toBeInTheDocument();
    });
    expect(screen.getAllByDisplayValue("Release graph").length).toBeGreaterThan(0);
    expect(screen.getAllByDisplayValue("plan").length).toBeGreaterThan(0);
    expect(screen.getAllByDisplayValue("codex").length).toBeGreaterThan(0);
    expect(screen.getAllByDisplayValue("Plan it").length).toBeGreaterThan(0);
  });

  it("applies advanced pipeline JSON and surfaces parse errors", async () => {
    const user = userEvent.setup();
    vi.mocked(fetch).mockImplementation(async (input) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url === "/api/graphs/graph-123") {
        return jsonResponse(graphPayload);
      }
      return jsonResponse({});
    });

    render(<GraphEditorPage />, {
      wrapper: createWrapper("/graphs/graph-123/edit", "/graphs/:graphId/edit"),
    });

    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "Release graph" })).toBeInTheDocument();
    });

    const editors = screen.getAllByTestId("monaco-editor");
    const pipelineEditor = editors[0];
    fireEvent.change(pipelineEditor, { target: { value: "{invalid" } });
    await user.click(screen.getByRole("button", { name: "Apply pipeline JSON" }));
    await waitFor(() => {
      expect(screen.getByText(/Expected property name or '}'/)).toBeInTheDocument();
    });

    fireEvent.change(pipelineEditor, {
      target: {
        value: JSON.stringify(
          {
            ...graphPayload.pipeline,
            name: "Updated graph",
            nodes: [{ id: "only", agent: "codex", prompt: "One", depends_on: [] }],
          },
          null,
          2,
        ),
      },
    });
    await user.click(screen.getByRole("button", { name: "Apply pipeline JSON" }));

    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "Updated graph" })).toBeInTheDocument();
    });
  });
});
