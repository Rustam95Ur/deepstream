import type { Camera, CameraList, CameraQuery, HistoryPage, HistoryQuery, NodeSettings, OutboundJob, SendEvent, Session, TriggerEvent, User, UserList, UserQuery, VideoHealth, Webhook, WebhookIn, WorkerStatus } from "./types";

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

function formatDetail(data: unknown, fallback: string): string {
  if (!data || typeof data !== "object" || !("detail" in data)) return fallback;
  const detail = (data as { detail: unknown }).detail;
  if (typeof detail === "string" && detail.trim()) return detail.trim();
  if (Array.isArray(detail)) {
    const parts = detail.map((item) => {
      if (typeof item === "string") return item;
      if (!item || typeof item !== "object") return "";
      const row = item as { loc?: unknown; msg?: unknown };
      const loc = Array.isArray(row.loc)
        ? row.loc.filter((part) => part !== "body" && part !== "query" && part !== "path").join(".")
        : "";
      const msg = row.msg != null ? String(row.msg) : "";
      if (loc && msg) return `${loc}: ${msg}`;
      return msg || loc;
    }).filter(Boolean);
    if (parts.length) return parts.join("; ");
  }
  return fallback;
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
    throw new ApiError(res.status, formatDetail(data, res.statusText || "Ошибка сервера"));
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
  upsertCamera: (body: { id: string; name: string; main_uri: string; enabled: boolean; enabled_triggers?: string[] | null }) =>
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
        enabled_triggers: body.enabled_triggers,
      }),
    }),
  deleteCamera: (id: string) =>
    request<void>(`/api/v1/cameras/${encodeURIComponent(id)}`, { method: "DELETE" }),
  worker: () => request<WorkerStatus>("/api/v1/worker"),
  videoHealth: () => request<VideoHealth>("/api/v1/video/health"),
  workerStart: () => request<WorkerStatus>("/api/v1/worker/start", { method: "POST" }),
  workerStop: () => request<WorkerStatus>("/api/v1/worker/stop", { method: "POST" }),
  historyTriggers: (query: HistoryQuery = {}) =>
    request<HistoryPage<TriggerEvent>>(`/api/v1/history/triggers${qs(query)}`),
  historySends: (query: HistoryQuery = {}) =>
    request<HistoryPage<SendEvent>>(`/api/v1/history/sends${qs(query)}`),
  historyOutbound: (query: HistoryQuery = {}) =>
    request<HistoryPage<OutboundJob>>(`/api/v1/history/outbound${qs(query)}`),
  triggerClip: (eventId: string) =>
    request<{ event_id: string; url: string; bucket: string; key: string }>(
      `/api/v1/history/triggers/${encodeURIComponent(eventId)}/clip`,
    ),
  resendTrigger: (eventId: string) =>
    request<{ event_id: string; queued: number }>(
      `/api/v1/history/triggers/${encodeURIComponent(eventId)}/resend`,
      { method: "POST" },
    ),
  retryOutbound: (jobId: string) =>
    request<OutboundJob>(`/api/v1/history/outbound/${encodeURIComponent(jobId)}/retry`, {
      method: "POST",
    }),
  webhooks: () => request<{ items: Webhook[] }>("/api/v1/webhooks"),
  createWebhook: (body: WebhookIn) =>
    request<Webhook>("/api/v1/webhooks", { method: "POST", body: JSON.stringify(body) }),
  updateWebhook: (id: string, body: WebhookIn) =>
    request<Webhook>(`/api/v1/webhooks/${encodeURIComponent(id)}`, {
      method: "PUT",
      body: JSON.stringify(body),
    }),
  deleteWebhook: (id: string) =>
    request<void>(`/api/v1/webhooks/${encodeURIComponent(id)}`, { method: "DELETE" }),
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
