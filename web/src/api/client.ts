const configuredBase = import.meta.env.VITE_API_BASE_URL ?? "";
export const API_BASE = configuredBase.replace(/\/$/, "");

let lastRequestId: string | null = null;

export class ApiError extends Error {
  readonly status: number;
  readonly detail: string;
  readonly requestId: string | null;

  constructor(status: number, detail: string, requestId: string | null) {
    super(detail);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
    this.requestId = requestId;
  }
}

export function apiUrl(path: string): string {
  return `${API_BASE}${path}`;
}

export function getLastRequestId(): string | null {
  return lastRequestId;
}

export function rememberRequestId(value: string | null): void {
  lastRequestId = value;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function detailFromPayload(payload: unknown): string {
  if (isRecord(payload) && typeof payload.detail === "string") {
    return payload.detail;
  }
  return "请求失败，请稍后重试。";
}

export async function apiRequest<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  let response: Response;
  try {
    const headers = new Headers(init.headers);
    if (!headers.has("Accept")) {
      headers.set("Accept", "application/json");
    }
    response = await fetch(apiUrl(path), {
      ...init,
      headers,
    });
  } catch {
    throw new ApiError(0, "无法连接后端服务，请确认服务已启动。", null);
  }

  const requestId = response.headers.get("X-Request-ID");
  rememberRequestId(requestId);

  if (response.status === 204) {
    return undefined as T;
  }

  let payload: unknown = null;
  const contentType = response.headers.get("content-type") ?? "";
  if (contentType.includes("application/json")) {
    try {
      payload = (await response.json()) as unknown;
    } catch {
      payload = null;
    }
  } else {
    payload = await response.text();
  }

  if (!response.ok) {
    throw new ApiError(
      response.status,
      detailFromPayload(payload),
      requestId,
    );
  }
  return payload as T;
}

export function userMessage(error: unknown): string {
  if (error instanceof ApiError) {
    return error.detail;
  }
  if (error instanceof Error && error.message) {
    return error.message;
  }
  return "请求失败，请稍后重试。";
}
