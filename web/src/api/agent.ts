import {
  ApiError,
  apiUrl,
  rememberRequestId,
} from "./client";
import { parseSseStream } from "../lib/sse";
import type {
  AgentStreamEvent,
  CitationsEventData,
  ErrorEventData,
  FinalEventData,
  TokenEventData,
  WorkflowEventData,
} from "./types";

const ALLOWED_EVENTS = new Set([
  "workflow",
  "token",
  "citations",
  "final",
  "error",
]);

function errorDetail(payload: string): string {
  try {
    const parsed: unknown = JSON.parse(payload);
    if (
      typeof parsed === "object" &&
      parsed !== null &&
      "detail" in parsed &&
      typeof parsed.detail === "string"
    ) {
      return parsed.detail;
    }
  } catch {
    // Keep the generic message for non-JSON errors.
  }
  return "流式请求失败，请稍后重试。";
}

export async function* streamAgent(
  question: string,
  topK: number,
  documentIds: string[],
  enableRewrite: boolean,
  signal: AbortSignal,
): AsyncGenerator<AgentStreamEvent> {
  let response: Response;
  try {
    response = await fetch(apiUrl("/api/v1/agent/ask/stream"), {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "text/event-stream",
      },
      body: JSON.stringify({
        question,
        top_k: topK,
        enable_rewrite: enableRewrite,
        ...(documentIds.length > 0 ? { document_ids: documentIds } : {}),
      }),
      signal,
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      throw error;
    }
    throw new ApiError(0, "无法连接后端服务，请确认服务已启动。", null);
  }

  const requestId = response.headers.get("X-Request-ID");
  rememberRequestId(requestId);

  if (!response.ok) {
    const text = await response.text();
    throw new ApiError(response.status, errorDetail(text), requestId);
  }
  if (!response.body) {
    throw new ApiError(0, "后端没有返回流式响应。", requestId);
  }

  for await (const message of parseSseStream(response.body)) {
    if (!ALLOWED_EVENTS.has(message.event)) {
      if (import.meta.env.DEV) {
        console.warn("忽略未知 SSE 事件", message.event);
      }
      continue;
    }
    let data: unknown;
    try {
      data = JSON.parse(message.data) as unknown;
    } catch {
      throw new ApiError(0, "流式响应格式错误。", requestId);
    }
    switch (message.event) {
      case "workflow":
        yield { event: "workflow", data: data as WorkflowEventData };
        break;
      case "token":
        yield { event: "token", data: data as TokenEventData };
        break;
      case "citations":
        yield { event: "citations", data: data as CitationsEventData };
        break;
      case "final":
        yield { event: "final", data: data as FinalEventData };
        break;
      case "error":
        yield { event: "error", data: data as ErrorEventData };
        break;
      default:
        break;
    }
  }
}
