import type { Camera, CameraList, NodeSettings, Session, WorkerStatus } from "./types";

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const res = await fetch(path, {
    ...init,
    headers,
    credentials: "include",
  });
  if (res.status === 204) {
    return undefined as T;
  }
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    const detail = data && typeof data === "object" && "detail" in data
      ? String((data as { detail: unknown }).detail)
      : res.statusText;
    throw new ApiError(res.status, detail);
  }
  return data as T;
}

export const api = {
  session: () => request<Session>("/api/v1/auth/session"),
  login: (token: string, token_confirm = "") =>
    request<Session>("/api/v1/auth/login", {
      method: "POST",
      body: JSON.stringify({ token, token_confirm }),
    }),
  logout: () => request<Session>("/api/v1/auth/logout", { method: "POST" }),
  settings: () => request<NodeSettings>("/api/v1/settings"),
  saveSettings: (body: NodeSettings) =>
    request<NodeSettings>("/api/v1/settings", {
      method: "PUT",
      body: JSON.stringify(body),
    }),
  cameras: () => request<CameraList>("/api/v1/cameras"),
  upsertCamera: (body: { id: string; name: string; main_uri: string; enabled: boolean }) =>
    request<Camera>("/api/v1/cameras", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  deleteCamera: (id: string) =>
    request<void>(`/api/v1/cameras/${encodeURIComponent(id)}`, { method: "DELETE" }),
  worker: () => request<WorkerStatus>("/api/v1/worker"),
  workerStart: () => request<WorkerStatus>("/api/v1/worker/start", { method: "POST" }),
  workerStop: () => request<WorkerStatus>("/api/v1/worker/stop", { method: "POST" }),
};
