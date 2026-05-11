import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { requestJson, requestText } from "./http";

describe("requestJson", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("makes GET request and returns parsed JSON", async () => {
    const mockData = [{ id: "run-1", status: "completed" }];
    vi.mocked(fetch).mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve(mockData),
    } as Response);

    const result = await requestJson<unknown[]>("/api/runs");
    
    expect(fetch).toHaveBeenCalledWith("/api/runs", { headers: new Headers() });
    expect(result).toEqual(mockData);
  });

  it("sets Content-Type header when body is provided", async () => {
    vi.mocked(fetch).mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve({ valid: true }),
    } as Response);

    await requestJson("/api/graphs/validate", {
      method: "POST",
      body: JSON.stringify({ pipeline: {} }),
    });

    const call = vi.mocked(fetch).mock.calls[0];
    const init = call[1] as RequestInit;
    expect(init.headers).toBeInstanceOf(Headers);
    expect((init.headers as Headers).get("Content-Type")).toBe("application/json");
  });

  it("does not override existing Content-Type header", async () => {
    vi.mocked(fetch).mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve({}),
    } as Response);

    const headers = new Headers();
    headers.set("Content-Type", "text/plain");

    await requestJson("/api/test", { method: "POST", body: "data", headers });

    const call = vi.mocked(fetch).mock.calls[0];
    const init = call[1] as RequestInit;
    expect((init.headers as Headers).get("Content-Type")).toBe("text/plain");
  });

  it("throws on non-ok response with detail", async () => {
    vi.mocked(fetch).mockResolvedValueOnce({
      ok: false,
      status: 404,
      json: () => Promise.resolve({ detail: "Not found" }),
    } as Response);

    await expect(requestJson("/api/runs/nonexistent")).rejects.toThrow("Not found");
  });

  it("throws on non-ok response without detail", async () => {
    vi.mocked(fetch).mockResolvedValueOnce({
      ok: false,
      status: 500,
      json: () => Promise.reject(new Error("invalid json")),
    } as Response);

    await expect(requestJson("/api/test")).rejects.toThrow("Request failed: 500");
  });
});

describe("requestText", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("returns text content", async () => {
    vi.mocked(fetch).mockResolvedValueOnce({
      ok: true,
      text: () => Promise.resolve("Hello, world!"),
    } as Response);

    const result = await requestText("/api/test.txt");
    
    expect(result).toBe("Hello, world!");
  });

  it("throws on non-ok response", async () => {
    vi.mocked(fetch).mockResolvedValueOnce({
      ok: false,
      status: 403,
    } as Response);

    await expect(requestText("/api/forbidden")).rejects.toThrow("Request failed: 403");
  });
});