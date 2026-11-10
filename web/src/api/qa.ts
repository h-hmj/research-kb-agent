import { apiRequest } from "./client";
import type { QAResponse } from "./types";

export function askQa(
  question: string,
  topK: number,
  documentIds: string[],
): Promise<QAResponse> {
  return apiRequest<QAResponse>("/api/v1/qa/ask", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      question,
      top_k: topK,
      ...(documentIds.length > 0 ? { document_ids: documentIds } : {}),
    }),
  });
}
