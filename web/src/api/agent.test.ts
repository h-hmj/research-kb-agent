import { afterEach, describe, expect, it, vi } from "vitest";

import { streamAgent } from "./agent";
import type { AgentStreamEvent } from "./types";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

function sseResponse(body: string): Response {
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      controller.enqueue(new TextEncoder().encode(body));
      controller.close();
    },
  });
  return new Response(stream, {
    status: 200,
    headers: {
      "Content-Type": "text/event-stream",
      "X-Request-ID": "stream-req",
    },
  });
}

describe("streamAgent", () => {
  it("parses known events, ignores unknown events, and preserves error events", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    const fetchMock = vi.fn(async (): Promise<Response> =>
      sseResponse(
        [
          'event: workflow\ndata: {"request_id":"r1","step":"retrieve_initial","message":"ok"}\n\n',
          'event: token\ndata: {"request_id":"r1","content":""}\n\n',
          'event: mystery\ndata: {"ignored":true}\n\n',
          'event: error\ndata: {"request_id":"r1","code":"llm_unavailable","message":"LLM 不可用"}\n\n',
        ].join(""),
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    const events: AgentStreamEvent[] = [];
    for await (const event of streamAgent(
      "question",
      5,
      [],
      true,
      new AbortController().signal,
    )) {
      events.push(event);
    }

    expect(events.map((event) => event.event)).toEqual([
      "workflow",
      "token",
      "error",
    ]);
    expect(events[1]).toMatchObject({ data: { content: "" } });
    expect(events[2]).toMatchObject({
      data: { code: "llm_unavailable", message: "LLM 不可用" },
    });
    expect(warn).toHaveBeenCalled();
  });
});
