import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AppRouter } from "./router";

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return function Wrapper({ children }: { children: React.ReactNode }) {
    return (
      <QueryClientProvider client={queryClient}>
        {children}
      </QueryClientProvider>
    );
  };
}

describe("AppRouter", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
    // Mock API responses
    vi.mocked(fetch).mockImplementation(async () => ({
      ok: true,
      json: () => Promise.resolve([]),
    } as Response));
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("redirects root path to /runs", async () => {
    render(<AppRouter />, { wrapper: createWrapper() });

    await waitFor(() => {
      // Should show Runs page content (empty state since no runs)
      expect(screen.getByText("Runs")).toBeInTheDocument();
    });
  });

  it("renders runs page at /runs", async () => {
    render(<AppRouter />, { wrapper: createWrapper() });

    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "Runs", level: 2 })).toBeInTheDocument();
    });
  });

  it("renders navigation links", async () => {
    render(<AppRouter />, { wrapper: createWrapper() });

    await waitFor(() => {
      expect(screen.getByText("No run selected")).toBeInTheDocument();
    });
  });
});
