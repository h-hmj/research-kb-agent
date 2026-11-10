import { apiRequest } from "./client";
import type { ToolResponse } from "./types";

export function runChecklist(
  goal: string,
  constraints: string[],
  topK: number,
  documentIds: string[],
): Promise<ToolResponse> {
  return apiRequest<ToolResponse>("/api/v1/tools/run", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      tool_name: "generate_experiment_checklist",
      arguments: {
        experiment_goal: goal,
        constraints,
        top_k: topK,
        ...(documentIds.length > 0 ? { document_ids: documentIds } : {}),
      },
    }),
  });
}

export function summarizeMeeting(
  title: string,
  focus: string,
  text: string,
): Promise<ToolResponse> {
  return apiRequest<ToolResponse>("/api/v1/tools/run", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      tool_name: "summarize_meeting_notes",
      arguments: {
        meeting_text: text,
        ...(title.trim() ? { meeting_title: title } : {}),
        ...(focus.trim() ? { focus } : {}),
      },
    }),
  });
}
