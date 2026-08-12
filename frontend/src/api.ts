import type { Camera, CameraList, CameraQuery, HistoryPage, HistoryQuery, NodeSettings, SendEvent, Session, TriggerEvent, User, UserList, UserQuery, WorkerStatus } from "./types";

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

function qs(query: Record<string, string | number | boolean | undefined>): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value === undefined || value === "") continue;
    params.set(key, String(value));
  }
  const encoded = params.toString();
  return encoded ? `?${encoded}` : "";
}

export const api = {
  session: () => request<Session>("/api/v1/auth/session"),
  login: (email: string, password: string, password_confirm = "") =>
    request<Session>("/api/v1/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password, password_confirm }),
    }),
  logout: () => request<Session>("/api/v1/auth/logout", { method: "POST" }),
  settings: () => request<NodeSettings>("/api/v1/settings"),
  saveSettings: (body: NodeSettings) =>
    request<NodeSettings>("/api/v1/settings", {
      method: "PUT",
      body: JSON.stringify(body),
    }),
  cameras: (query: CameraQuery = {}) => request<CameraList>(`/api/v1/cameras${qs(query)}`),
  upsertCamera: (body: { id: string; name: string; main_uri: string; enabled: boolean }) =>
    request<Camera>("/api/v1/cameras", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  updateCamera: (id: string, body: Camera) =>
    request<Camera>(`/api/v1/cameras/${encodeURIComponent(id)}`, {
      method: "PUT",
      body: JSON.stringify({
        id: body.id,
        name: body.name,
        main_uri: body.main_uri,
        enabled: body.enabled,
        external_id: body.external_id,
        meta: body.meta,
      }),
    }),
  deleteCamera: (id: string) =>
    request<void>(`/api/v1/cameras/${encodeURIComponent(id)}`, { method: "DELETE" }),
  worker: () => request<WorkerStatus>("/api/v1/worker"),
  workerStart: () => request<WorkerStatus>("/api/v1/worker/start", { method: "POST" }),
  workerStop: () => request<WorkerStatus>("/api/v1/worker/stop", { method: "POST" }),
  historyTriggers: (query: HistoryQuery = {}) =>
    request<HistoryPage<TriggerEvent>>(`/api/v1/history/triggers${qs(query)}`),
  historySends: (query: HistoryQuery = {}) =>
    request<HistoryPage<SendEvent>>(`/api/v1/history/sends${qs(query)}`),
  users: (query: UserQuery = {}) => request<UserList>(`/api/v1/users${qs(query)}`),
  getUser: (id: string) => request<User>(`/api/v1/users/${encodeURIComponent(id)}`),
  createUser: (body: { email: string; password: string; name: string }) =>
    request<User>("/api/v1/users", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  updateUser: (id: string, body: { email: string; name: string; password: string }) =>
    request<User>(`/api/v1/users/${encodeURIComponent(id)}`, {
      method: "PUT",
      body: JSON.stringify(body),
    }),
  deleteUser: (id: string) =>
    request<void>(`/api/v1/users/${encodeURIComponent(id)}`, { method: "DELETE" }),
};
