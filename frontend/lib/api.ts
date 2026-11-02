// Client for the X backend. All calls go through the same-origin /api proxy.

export class ApiError extends Error {
  status: number;
  details: unknown;
  constructor(status: number, message: string, details?: unknown) {
    super(message);
    this.status = status;
    this.details = details;
  }
}

function csrf(): string {
  if (typeof document === "undefined") return "";
  const m = document.cookie.match(/(?:^|; )x_csrf=([^;]+)/);
  return m ? decodeURIComponent(m[1]) : "";
}

function messageFrom(detail: unknown, fallback: string): string {
  if (!detail) return fallback;
  if (typeof detail === "string") return detail;
  if (typeof detail === "object") {
    const d = detail as { message?: string; errors?: unknown[] };
    const errs = Array.isArray(d.errors)
      ? d.errors
          .map((e) => (typeof e === "string" ? e : `${(e as { field?: string }).field ?? ""} ${(e as { message?: string }).message ?? ""}`.trim()))
          .join("; ")
      : "";
    return [d.message, errs].filter(Boolean).join(": ") || fallback;
  }
  return fallback;
}

async function request<T>(method: string, path: string, body?: unknown, isForm = false): Promise<T> {
  const headers: Record<string, string> = {};
  if (method !== "GET") headers["x-csrf-token"] = csrf();
  if (body !== undefined && !isForm) headers["content-type"] = "application/json";
  let res: Response;
  try {
    res = await fetch(`/api${path}`, {
      method,
      headers,
      credentials: "same-origin",
      body: body === undefined ? undefined : isForm ? (body as FormData) : JSON.stringify(body),
      cache: "no-store",
    });
  } catch {
    throw new ApiError(0, "Cannot reach the X backend. Check that the API service is running.");
  }
  const text = await res.text();
  let data: unknown = undefined;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = text;
    }
  }
  if (!res.ok) {
    const detail = (data as { detail?: unknown })?.detail ?? data;
    throw new ApiError(res.status, messageFrom(detail, `Request failed (${res.status})`), detail);
  }
  return data as T;
}

export const api = {
  get: <T>(path: string) => request<T>("GET", path),
  post: <T>(path: string, body?: unknown) => request<T>("POST", path, body ?? {}),
  put: <T>(path: string, body?: unknown) => request<T>("PUT", path, body ?? {}),
  patch: <T>(path: string, body?: unknown) => request<T>("PATCH", path, body ?? {}),
  del: <T>(path: string) => request<T>("DELETE", path),
  form: <T>(path: string, form: FormData, method = "POST") => request<T>(method, path, form, true),
};

export function wsBase(): string {
  const configured = process.env.NEXT_PUBLIC_WS_BASE;
  if (configured) return configured.replace(/\/$/, "");
  if (typeof window === "undefined") return "";
  // Local development: the API runs on :8000 next to Next on :3000.
  const proto = window.location.protocol === "https:" ? "wss" : "ws";
  const host = window.location.port === "3000" ? `${window.location.hostname}:8000` : window.location.host;
  return `${proto}://${host}`;
}
