import { ENDPOINTS, type EndpointKey } from "@apppilot/contracts";
import { IS_MOCK } from "@/lib/env";

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

let mockTransportPromise: Promise<Transport> | null = null;
let liveTransportPromise: Promise<Transport> | null = null;

export async function getTransport(): Promise<Transport> {
  if (!IS_MOCK) {
    // Maps contract endpoints onto the FastAPI backend (see ./live).
    liveTransportPromise ??= import("./live").then((m) => m.liveTransport);
    return liveTransportPromise;
  }
  // Loaded lazily so the mock adapter is never part of a live-mode bundle path.
  mockTransportPromise ??= import("./mock/transport").then((m) => m.mockTransport);
  return mockTransportPromise;
}
