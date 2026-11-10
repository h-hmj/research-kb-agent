import { apiRequest } from "./client";
import type {
  EvaluationListItem,
  EvaluationMode,
  EvaluationReport,
  EvaluationRunResponse,
} from "./types";

export function runEvaluation(
  datasetName: string,
  mode: EvaluationMode,
  topK: number,
): Promise<EvaluationRunResponse> {
  return apiRequest<EvaluationRunResponse>("/api/v1/evaluations/run", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      dataset_name: datasetName,
      mode,
      top_k: topK,
    }),
  });
}

export function listEvaluations(): Promise<EvaluationListItem[]> {
  return apiRequest<EvaluationListItem[]>("/api/v1/evaluations");
}

export function getEvaluation(runId: string): Promise<EvaluationReport> {
  return apiRequest<EvaluationReport>(
    `/api/v1/evaluations/${encodeURIComponent(runId)}`,
  );
}
