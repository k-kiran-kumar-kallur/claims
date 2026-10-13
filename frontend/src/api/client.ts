/** Typed fetch wrapper: in-memory JWT, silent refresh via httpOnly cookie, RFC 7807 error parsing. */

export class ApiError extends Error {
  status: number;
  correlationId?: string;
  errors?: { loc: (string | number)[]; msg: string }[];
  constructor(status: number, message: string, correlationId?: string, errors?: ApiError["errors"]) {
    super(message);
    this.status = status;
    this.correlationId = correlationId;
    this.errors = errors;
  }
}

let accessToken: string | null = null;
let refreshing: Promise<string | null> | null = null;
let onUnauthorized: (() => void) | null = null;

export const setAccessToken = (t: string | null) => (accessToken = t);
export const getAccessToken = () => accessToken;
export const setUnauthorizedHandler = (fn: () => void) => (onUnauthorized = fn);

const BASE = "/api/v1";

export async function refreshAccessToken(): Promise<string | null> {
  if (!refreshing) {
    refreshing = fetch(`${BASE}/auth/refresh`, {
      method: "POST",
      credentials: "include",
      headers: { "X-Requested-With": "XMLHttpRequest" },
    })
      .then(async (r) => {
        if (!r.ok) return null;
        const body = await r.json();
        accessToken = body.data.access_token;
        return accessToken;
      })
      .catch(() => null)
      .finally(() => {
        refreshing = null;
      });
  }
  return refreshing;
}

async function parseError(r: Response): Promise<ApiError> {
  try {
    const body = await r.json();
    return new ApiError(r.status, body.detail || body.title || r.statusText, body.correlation_id, body.errors);
  } catch {
    return new ApiError(r.status, r.statusText);
  }
}

export async function request<T = unknown>(path: string, init: RequestInit & { raw?: boolean } = {}, retry = true): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("X-Requested-With", "XMLHttpRequest");
  if (accessToken) headers.set("Authorization", `Bearer ${accessToken}`);
  if (init.body && !(init.body instanceof FormData) && !(init.body instanceof Blob) && !headers.has("Content-Type"))
    headers.set("Content-Type", "application/json");
  const r = await fetch(`${BASE}${path}`, { ...init, headers, credentials: "include" });
  if (r.status === 401 && retry && !path.startsWith("/auth/")) {
    const t = await refreshAccessToken();
    if (t) return request<T>(path, init, false);
    onUnauthorized?.();
  }
  if (!r.ok) throw await parseError(r);
  if (init.raw) return r as unknown as T;
  if (r.status === 204) return undefined as T;
  return (await r.json()) as T;
}

export interface Envelope<T> {
  data: T;
  meta: Record<string, unknown>;
}

export const api = {
  get: <T>(path: string) => request<Envelope<T>>(path).then((e) => e.data),
  getEnv: <T>(path: string) => request<Envelope<T>>(path),
  post: <T>(path: string, body?: unknown) =>
    request<Envelope<T>>(path, { method: "POST", body: body instanceof FormData ? body : JSON.stringify(body ?? {}) }).then((e) => e?.data),
  put: <T>(path: string, body?: unknown) => request<Envelope<T>>(path, { method: "PUT", body: JSON.stringify(body ?? {}) }).then((e) => e.data),
  patch: <T>(path: string, body?: unknown) => request<Envelope<T>>(path, { method: "PATCH", body: JSON.stringify(body ?? {}) }).then((e) => e.data),
  blob: async (path: string) => (await request<Response>(path, { raw: true })).blob(),
};

export function qs(params: Record<string, string | number | boolean | undefined | null>): string {
  const p = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== "") p.set(k, String(v));
  });
  const s = p.toString();
  return s ? `?${s}` : "";
}

export async function downloadFile(path: string, filename: string) {
  const blob = await api.blob(path);
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}
