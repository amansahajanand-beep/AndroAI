/**
 * Low-level calls to the FastAPI backend (same-origin via the Next.js rewrite, so the
 * httpOnly session cookies stay first-party and JavaScript never sees a token).
 *
 * - Sends cookies on every request; the browser adds the Origin header the backend's CSRF
 *   check requires.
 * - On a 401 (access cookie expired) it refreshes the session once (single-flight, shared by
 *   concurrent requests) and retries; if that fails the 401 surfaces and the app redirects to login.
 * - Maps the backend error envelope onto the codes/fields the screens expect.
 */
import type { EndpointKey } from "@apppilot/contracts";
import { ApiError, isApiErrorBody } from "../errors";

export type Query = Record<string, string | number | boolean | undefined | null>;

export interface BackendOptions {
  key: EndpointKey;
  query?: Query;
  body?: unknown;
  signal?: AbortSignal;
}

const NO_REFRESH = /^\/api\/v1\/auth\/(login|register|refresh|forgot-password|reset-password|logout)$/;

function url(path: string, query: Query = {}): string {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(query)) if (v !== undefined && v !== null && v !== "") qs.set(k, String(v));
  const s = qs.toString();
  return s ? `${path}?${s}` : path;
}

let refreshing: Promise<boolean> | null = null;

/** Rotates the refresh cookie. Resolves false when the session is gone. */
export function refreshSession(): Promise<boolean> {
  refreshing ??= fetch("/api/v1/auth/refresh", { method: "POST", credentials: "include", headers: { Accept: "application/json" } })
    .then((r) => r.ok)
    .catch(() => false)
    .finally(() => {
      refreshing = null;
    });
  return refreshing;
}

const FIELD_NAMES: Record<string, string> = {
  display_name: "name",
  new_password: "password",
  min_sdk: "minSdk",
  target_sdk: "targetSdk",
  package_name: "packageName",
};

function fieldsFromDetails(details: unknown): Record<string, string> | undefined {
  if (!Array.isArray(details)) return undefined;
  const out: Record<string, string> = {};
  for (const d of details as { loc?: unknown[]; msg?: string }[]) {
    const last = String(d.loc?.[d.loc.length - 1] ?? "");
    if (last && last !== "body") out[FIELD_NAMES[last] ?? last] ??= d.msg ?? "Invalid value";
  }
  return Object.keys(out).length ? out : undefined;
}

/** Translates backend error codes to the codes the screens already handle. */
function toApiError(status: number, data: unknown, key: EndpointKey): ApiError {
  if (!isApiErrorBody(data)) {
    // No envelope: proxy failure or route not deployed.
    const unreachable = status === 404 || status >= 500;
    return new ApiError({
      status,
      code: unreachable ? "backend_unavailable" : "http_error",
      message: unreachable ? "This part of the API isn't available yet." : `Request failed (${status}).`,
      endpoint: key,
      unreachable,
    });
  }
  const { code, message, details } = data.error as { code: string; message: string; details?: unknown };
  const base = { status, message, endpoint: key };
  switch (code) {
    case "invalid_credentials":
      return new ApiError({ ...base, code: "auth.invalid_credentials", message: key === "users.changePassword" ? message : "That email and password don't match an account." });
    case "email_taken":
      return new ApiError({ ...base, code: "auth.email_taken", message: "An account with this email already exists.", fields: { email: "This email is already registered." } });
    case "weak_password":
      return new ApiError({ ...base, code: "auth.weak_password", fields: { password: message } });
    case "email_not_verified":
      return new ApiError({ ...base, code: "auth.email_not_verified" });
    case "invalid_token":
      if (key === "auth.resetPassword") return new ApiError({ ...base, code: "auth.reset_token_invalid", message: "This reset link is invalid or has expired. Request a new one." });
      return new ApiError({ ...base, code: "auth.required", message: "Sign in to continue." });
    case "not_authenticated":
    case "invalid_refresh_token":
      return new ApiError({ ...base, code: "auth.required", message: "Sign in to continue." });
    case "conflict":
      return new ApiError({ ...base, code: "file.version_conflict", message: "This file changed since you opened it." });
    case "validation_error":
      return new ApiError({ ...base, code, fields: fieldsFromDetails(details) });
    default:
      return new ApiError({ ...base, code });
  }
}

export async function backend<T>(method: string, path: string, opts: BackendOptions): Promise<T> {
  const attempt = async (): Promise<Response> => {
    try {
      return await fetch(url(path, opts.query), {
        method,
        credentials: "include",
        headers: {
          Accept: "application/json",
          ...(opts.body !== undefined ? { "Content-Type": "application/json" } : {}),
        },
        body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
        signal: opts.signal,
      });
    } catch (e) {
      if (e instanceof DOMException && e.name === "AbortError") throw e;
      throw new ApiError({
        status: 0,
        code: "network",
        message: "Can't reach the AppPilot API. Check your connection or try again shortly.",
        endpoint: opts.key,
        unreachable: true,
      });
    }
  };

  let res = await attempt();
  if (res.status === 401 && !NO_REFRESH.test(path) && (await refreshSession())) res = await attempt();

  if (res.status === 204) return undefined as T;
  const text = await res.text();
  let data: unknown;
  try {
    data = text ? JSON.parse(text) : undefined;
  } catch {
    data = text;
  }
  if (!res.ok) throw toApiError(res.status, data, opts.key);
  return data as T;
}

export const notImplemented = (key: EndpointKey, what?: string): never => {
  throw new ApiError({
    status: 501,
    code: "not_implemented",
    message: what ?? "The backend for this feature isn't built yet.",
    endpoint: key,
  });
};
