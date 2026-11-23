import type { ApiErrorBody, EndpointKey } from "@apppilot/contracts";

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly fields?: Record<string, string>;
  readonly endpoint?: EndpointKey;
  readonly requestId?: string;
  /** True when the response did not come from our API (proxy error, missing route, offline). */
  readonly unreachable: boolean;

  constructor(opts: {
    status: number;
    code: string;
    message: string;
    fields?: Record<string, string>;
    endpoint?: EndpointKey;
    requestId?: string;
    unreachable?: boolean;
  }) {
    super(opts.message);
    this.name = "ApiError";
    this.status = opts.status;
    this.code = opts.code;
    this.fields = opts.fields;
    this.endpoint = opts.endpoint;
    this.requestId = opts.requestId;
    this.unreachable = opts.unreachable ?? false;
  }
}

export function isApiErrorBody(v: unknown): v is ApiErrorBody {
  return (
    typeof v === "object" &&
    v !== null &&
    "error" in v &&
    typeof (v as ApiErrorBody).error?.code === "string"
  );
}

/**
 * The endpoint isn't available yet: backend offline, route not deployed
 * (404 without our error envelope), or explicitly not implemented (501).
 * Screens render a "waiting for backend" state instead of a generic error.
 */
export function isPendingBackend(err: unknown): err is ApiError {
  return (
    err instanceof ApiError &&
    (err.unreachable || err.status === 501 || err.code === "not_implemented")
  );
}

export function isUnauthorized(err: unknown): boolean {
  return err instanceof ApiError && err.status === 401;
}

export function errorMessage(err: unknown): string {
  if (err instanceof ApiError) return err.message;
  if (err instanceof Error) return err.message;
  return "Something went wrong.";
}
