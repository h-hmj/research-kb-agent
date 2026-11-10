import { afterEach, describe, expect, it, vi } from "vitest";

import { apiRequest, getLastRequestId } from "./client";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("apiRequest", () => {
  it("saves X-Request-ID from the response", async () => {
    const fetchMock = vi.fn(async (): Promise<Response> =>
      new Response(JSON.stringify({ ok: true }), {
        status: 200,
        headers: {
          "Content-Type": "application/json",
          "X-Request-ID": "req-123",
        },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const payload = await apiRequest<{ ok: boolean }>("/api/v1/health");

    expect(payload.ok).toBe(true);
    expect(getLastRequestId()).toBe("req-123");
  });

  it("turns FastAPI detail into a user-readable error", async () => {
    const fetchMock = vi.fn(async (): Promise<Response> =>
      new Response(JSON.stringify({ detail: "文档不存在" }), {
        status: 404,
        headers: {
          "Content-Type": "application/json",
          "X-Request-ID": "req-404",
        },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(apiRequest("/api/v1/documents/missing")).rejects.toMatchObject({
      status: 404,
      detail: "文档不存在",
      requestId: "req-404",
    });
  });

  it("maps network failures to a friendly message", async () => {
    const fetchMock = vi.fn(async (): Promise<Response> => {
      throw new Error("offline");
    });
    vi.stubGlobal("fetch", fetchMock);

    await expect(apiRequest("/api/v1/health")).rejects.toMatchObject({
      status: 0,
      detail: "无法连接后端服务，请确认服务已启动。",
    });
  });
});
