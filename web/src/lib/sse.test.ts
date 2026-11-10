import { describe, expect, it } from "vitest";

import { SseParser } from "./sse";

describe("SseParser", () => {
  it("parses events split across chunks", () => {
    const parser = new SseParser();
    expect(parser.feed("event: work")).toEqual([]);
    expect(parser.feed("flow\ndata: {\"step\":\"x\"}\n\n")).toEqual([
      { event: "workflow", data: "{\"step\":\"x\"}" },
    ]);
  });

  it("keeps multiple events in order", () => {
    const parser = new SseParser();
    const messages = parser.feed(
      "event: token\ndata: one\n\nevent: token\ndata: two\n\n",
    );
    expect(messages.map((item) => item.data)).toEqual(["one", "two"]);
  });

  it("joins multiline data and ignores comments", () => {
    const parser = new SseParser();
    expect(
      parser.feed(": heartbeat\n\nevent: token\ndata: a\ndata: b\n\n"),
    ).toEqual([{ event: "token", data: "a\nb" }]);
  });
});
