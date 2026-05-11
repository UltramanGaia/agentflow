import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { vi } from "vitest";
import { StatusBadge } from "./status/StatusBadge";
import { AgentNode } from "./graph/AgentNode";
import { EmptyState, ErrorState, LoadingState } from "./feedback/States";

vi.mock("reactflow", () => ({
  Handle: () => <span data-testid="rf-handle" />,
  Position: { Left: "left", Right: "right" },
}));

function wrapper({ children }: { children: React.ReactNode }) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return (
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>{children}</MemoryRouter>
    </QueryClientProvider>
  );
}

describe("StatusBadge", () => {
  it("renders completed status", () => {
    render(<StatusBadge status="completed" />, { wrapper });
    expect(screen.getByText("completed")).toBeInTheDocument();
  });

  it("renders running status", () => {
    render(<StatusBadge status="running" />, { wrapper });
    expect(screen.getByText("running")).toBeInTheDocument();
  });

  it("renders failed status", () => {
    render(<StatusBadge status="failed" />, { wrapper });
    expect(screen.getByText("failed")).toBeInTheDocument();
  });

  it("renders pending status", () => {
    render(<StatusBadge status="pending" />, { wrapper });
    expect(screen.getByText("pending")).toBeInTheDocument();
  });

  it("renders unknown status as-is", () => {
    render(<StatusBadge status="unknown-status" />, { wrapper });
    expect(screen.getByText("unknown-status")).toBeInTheDocument();
  });
});

describe("EmptyState", () => {
  it("renders title and description", () => {
    render(<EmptyState title="No items" description="Create one to get started." />, { wrapper });
    
    expect(screen.getByText("No items")).toBeInTheDocument();
    expect(screen.getByText("Create one to get started.")).toBeInTheDocument();
  });

  it("renders without description", () => {
    render(<EmptyState title="Empty" />, { wrapper });
    
    expect(screen.getByText("Empty")).toBeInTheDocument();
  });
});

describe("ErrorState", () => {
  it("renders error message", () => {
    render(<ErrorState message="Something went wrong" />, { wrapper });
    
    expect(screen.getByText("Error")).toBeInTheDocument();
    expect(screen.getByText("Something went wrong")).toBeInTheDocument();
  });
});

describe("LoadingState", () => {
  it("renders loading message", () => {
    render(<LoadingState>Loading data...</LoadingState>, { wrapper });
    
    expect(screen.getByText("Loading data...")).toBeInTheDocument();
  });

  it("renders with default message", () => {
    render(<LoadingState />, { wrapper });
    
    expect(screen.getByText("Loading...")).toBeInTheDocument();
  });
});

describe("AgentNode", () => {
  it("opens detail action from the node card", async () => {
    const user = userEvent.setup();
    const onInspect = vi.fn();

    render(
      <AgentNode
        data={{ title: "apply", agent: "gaia", status: "failed", onInspect }}
        dragging={false}
        id="apply"
        isConnectable
        selected={false}
        type="agentNode"
        xPos={0}
        yPos={0}
        zIndex={0}
      />,
      { wrapper },
    );

    await user.click(screen.getByRole("button", { name: "Inspect apply" }));
    expect(onInspect).toHaveBeenCalledTimes(1);
  });
});
