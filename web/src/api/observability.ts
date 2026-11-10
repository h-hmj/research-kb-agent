import { apiRequest } from "./client";
import type { HealthResponse, MetricsSnapshot } from "./types";

export function getHealth(): Promise<HealthResponse> {
  return apiRequest<HealthResponse>("/api/v1/health");
}

export function getMetrics(): Promise<MetricsSnapshot> {
  return apiRequest<MetricsSnapshot>(
    "/api/v1/observability/metrics",
  );
}
