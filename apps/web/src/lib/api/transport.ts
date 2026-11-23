import { ENDPOINTS, type EndpointKey } from "@apppilot/contracts";
import { IS_MOCK } from "@/lib/env";
import { ApiError, isApiErrorBody } from "./errors";

export type Query = Record<string, string | number | boolean | undefined | null>;

export interface RequestOptions {
  params?: Record<string, string>;
  query?: Query;
  body?: unknown;
  signal?: AbortSignal;
}

export interface ResolvedRequest {
  key: EndpointKey;
  method: string;
  /** Path with params filled in, no query string. */
  path: string;
  params: Record<string, string>;
  query: Query;
  body?: unknown;
  signal?: AbortSignal;
}

export interface Transport {
  request<T>(req: ResolvedRequest): Promise<T>;
}

/** Fills `{param}` placeholders and strips the documentation-only query hint. */
export function resolvePath(key: EndpointKey, params: Record<string, string> = {}): string {
  const template = ENDPOINTS[key].path.split("?")[0] ?? "";
  return template.replace(/\{(\w+)\}/g, (_, name: string) => {
    const v = params[name];
    if (v == null) throw new Error(`Missing path param "${name}" for ${key}`);
    return encodeURIComponent(v);
  });
}

export function buildUrl(path: string, query: Query = {}): string {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(query)) {
    if (v !== undefined && v !== null && v !== "") qs.set(k, String(v));
  }
  const s = qs.toString();
  return s ? `${path}?${s}` : path;
}

const httpTransport: Transport = {
  async request<T>(req: ResolvedRequest): Promise<T> {
    let res: Response;
    try {
      res = await fetch(buildUrl(req.path, req.query), {
        method: req.method,
        credentials: "include",
        headers: {
          Accept: "application/json",
          ...(req.body !== undefined ? { "Content-Type": "application/json" } : {}),
        },
        body: req.body !== undefined ? JSON.stringify(req.body) : undefined,
        signal: req.signal,
      });
    } catch (e) {
      if (e instanceof DOMException && e.name === "AbortError") throw e;
      throw new ApiError({
        status: 0,
        code: "network",
        message: "Can't reach the AppPilot API. Check your connection or try again shortly.",
        endpoint: req.key,
        unreachable: true,
      });
    }

    if (res.status === 204) return undefined as T;

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
      if (isApiErrorBody(data)) {
        throw new ApiError({
          status: res.status,
          code: data.error.code,
          message: data.error.message,
          fields: data.error.fields,
          requestId: data.error.requestId,
          endpoint: req.key,
        });
      }
      // No envelope: proxy failure or route not deployed yet.
      const unreachable = res.status === 404 || res.status >= 500;
      throw new ApiError({
        status: res.status,
        code: unreachable ? "backend_unavailable" : "http_error",
        message: unreachable
          ? "This part of the API isn't available yet."
          : `Request failed (${res.status}).`,
        endpoint: req.key,
        unreachable,
      });
    }
    return data as T;
  },
};

let mockTransportPromise: Promise<Transport> | null = null;

export async function getTransport(): Promise<Transport> {
  if (!IS_MOCK) return httpTransport;
  // Loaded lazily so the mock adapter is never part of a live-mode bundle path.
  mockTransportPromise ??= import("./mock/transport").then((m) => m.mockTransport);
  return mockTransportPromise;
}
