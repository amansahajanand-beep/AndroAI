import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { EndpointKey } from "@apppilot/contracts";
import { ENDPOINTS } from "@apppilot/contracts";
import { ApiError, isPendingBackend } from "../errors";
import { resolvePath, type ResolvedRequest } from "../transport";
import { liveTransport } from "./index";

interface Call {
  method: string;
  url: string;
  body?: unknown;
}
type Responder = (call: Call) => { status?: number; body?: unknown } | undefined;

let calls: Call[];
let responders: Responder[];

function stubFetch() {
  calls = [];
  responders = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string, init?: RequestInit) => {
      const call: Call = { method: init?.method ?? "GET", url: String(input), body: init?.body ? JSON.parse(String(init.body)) : undefined };
      calls.push(call);
      for (const r of responders) {
        const out = r(call);
        if (out) {
          const status = out.status ?? 200;
          return new Response(status === 204 ? null : JSON.stringify(out.body ?? {}), { status });
        }
      }
      return new Response(JSON.stringify({ error: { code: "not_found", message: "nope" } }), { status: 404 });
    }),
  );
}

const req = (key: EndpointKey, o: Partial<ResolvedRequest> = {}): ResolvedRequest => ({
  key,
  method: ENDPOINTS[key].method,
  path: resolvePath(key, o.params),
  params: o.params ?? {},
  query: o.query ?? {},
  body: o.body,
});
const call = <T>(key: EndpointKey, o: Partial<ResolvedRequest> = {}) => liveTransport.request<T>(req(key, o));
const on = (method: string, path: string, body: unknown, status = 200): Responder =>
  (c) => (c.method === method && c.url.split("?")[0] === path ? { status, body } : undefined);
const err = (code: string, message = "m", details?: unknown) => ({ error: { code, message, details } });

const BUSER = { id: "u1", email: "ada@example.com", display_name: "Ada", is_active: true, email_verified: true, roles: ["user"], created_at: "t" };

beforeEach(stubFetch);
afterEach(() => vi.unstubAllGlobals());

describe("session and auth", () => {
  it("maps the session", async () => {
    responders.push(on("GET", "/api/v1/auth/session", { user: BUSER, expires_at: "2026-01-01T00:30:00Z" }));
    expect(await call("auth.session")).toMatchObject({ user: { name: "Ada", role: "user" }, expiresAt: "2026-01-01T00:30:00Z" });
  });

  it("login sends remember and returns the user (cookies carry the session)", async () => {
    responders.push(on("POST", "/api/v1/auth/login", { user: BUSER, tokens: { access_expires_at: "exp", access_token: "SECRET" } }));
    const s = await call<Record<string, unknown>>("auth.login", { body: { email: "a@b.c", password: "pw", remember: false } });
    expect(calls[0]!.body).toEqual({ email: "a@b.c", password: "pw", remember: false });
    expect(s).toMatchObject({ expiresAt: "exp", user: { email: "ada@example.com" } });
    expect(JSON.stringify(s)).not.toContain("SECRET"); // tokens never reach app state
  });

  it("register creates the account then signs in", async () => {
    responders.push(on("POST", "/api/v1/auth/register", BUSER, 201), on("POST", "/api/v1/auth/login", { user: BUSER, tokens: { access_expires_at: "exp" } }));
    await call("auth.register", { body: { name: "Ada", email: "a@b.c", password: "long-enough-pw", acceptTerms: true } });
    expect(calls.map((c) => `${c.method} ${c.url}`)).toEqual(["POST /api/v1/auth/register", "POST /api/v1/auth/login"]);
    expect(calls[0]!.body).toEqual({ email: "a@b.c", password: "long-enough-pw", display_name: "Ada" });
  });

  it("register requires accepting the terms without calling the server", async () => {
    await expect(call("auth.register", { body: { name: "A", email: "a@b.c", password: "x", acceptTerms: false } })).rejects.toMatchObject({ code: "validation_error" });
    expect(calls).toHaveLength(0);
  });

  it("translates backend errors to the codes screens handle", async () => {
    responders.push(on("POST", "/api/v1/auth/login", err("invalid_credentials"), 401));
    await expect(call("auth.login", { body: { email: "a@b.c", password: "x" } })).rejects.toMatchObject({ status: 401, code: "auth.invalid_credentials" });
    responders.length = 0;
    responders.push(on("POST", "/api/v1/auth/register", err("email_taken"), 409));
    await expect(call("auth.register", { body: { name: "A", email: "a@b.c", password: "x", acceptTerms: true } })).rejects.toMatchObject({
      code: "auth.email_taken", fields: { email: expect.any(String) },
    });
    responders.length = 0;
    responders.push(on("POST", "/api/v1/auth/reset-password", err("invalid_token"), 400));
    await expect(call("auth.resetPassword", { body: { token: "t", password: "x" } })).rejects.toMatchObject({ code: "auth.reset_token_invalid" });
    responders.length = 0;
    responders.push(on("POST", "/api/v1/auth/register", err("validation_error", "Invalid request", [{ loc: ["body", "display_name"], msg: "too long" }]), 422));
    await expect(call("auth.register", { body: { name: "A", email: "a@b.c", password: "x", acceptTerms: true } })).rejects.toMatchObject({ fields: { name: "too long" } });
  });
});

describe("401 handling", () => {
  it("refreshes the session once and retries", async () => {
    let first = true;
    responders.push(
      (c) => (c.url === "/api/v1/auth/session" && first ? ((first = false), { status: 401, body: err("invalid_token") }) : undefined),
      on("POST", "/api/v1/auth/refresh", { access_token: "x" }),
      on("GET", "/api/v1/auth/session", { user: BUSER, expires_at: "e" }),
    );
    expect(await call("auth.session")).toMatchObject({ expiresAt: "e" });
    expect(calls.map((c) => `${c.method} ${c.url}`)).toEqual(["GET /api/v1/auth/session", "POST /api/v1/auth/refresh", "GET /api/v1/auth/session"]);
  });

  it("shares one refresh between concurrent requests", async () => {
    let expired = 2;
    responders.push(
      (c) => (c.method === "GET" && c.url.startsWith("/api/v1/projects") && expired-- > 0 ? { status: 401, body: err("invalid_token") } : undefined),
      on("POST", "/api/v1/auth/refresh", {}),
      on("GET", "/api/v1/projects", { items: [], total: 0, limit: 100, offset: 0 }),
      on("GET", "/api/v1/projects/p1", { id: "p1", name: "A", description: null, source_type: "zip", status: "active", metadata: {}, storage_bytes: 0, active_jobs: 0, last_build: null, created_at: "t", updated_at: "t" }),
    );
    await Promise.all([call("projects.list"), call("projects.get", { params: { projectId: "p1" } })]);
    expect(calls.filter((c) => c.url === "/api/v1/auth/refresh")).toHaveLength(1);
  });

  it("surfaces auth.required when the refresh fails (app then redirects to login)", async () => {
    responders.push(on("GET", "/api/v1/users/me", err("invalid_token"), 401), on("POST", "/api/v1/auth/refresh", err("invalid_refresh_token"), 401));
    const e = await call("users.me").catch((x) => x);
    expect(e).toBeInstanceOf(ApiError);
    expect(e).toMatchObject({ status: 401, code: "auth.required" });
  });

  it("does not try to refresh failed logins", async () => {
    responders.push(on("POST", "/api/v1/auth/login", err("invalid_credentials"), 401));
    await call("auth.login", { body: { email: "a@b.c", password: "x" } }).catch(() => undefined);
    expect(calls.some((c) => c.url.endsWith("/refresh"))).toBe(false);
  });
});

describe("pending features", () => {
  it("answers 501 not_implemented for endpoints with no backend, which screens show as 'waiting'", async () => {
    for (const key of ["billing.plans", "usage.summary", "preview.start", "ui.screens", "projects.terminal.create", "tests.cases"] as const) {
      const e = await call(key, { params: { projectId: "p", taskId: "t", jobId: "j" } }).catch((x) => x);
      expect(e).toMatchObject({ status: 501, code: "not_implemented", endpoint: key });
      expect(isPendingBackend(e)).toBe(true);
    }
    expect(calls).toHaveLength(0);
  });

  it("registry marks exactly the unhandled endpoints as planned", async () => {
    const planned = (Object.keys(ENDPOINTS) as EndpointKey[]).filter((k) => ENDPOINTS[k].status === "planned" && ENDPOINTS[k].method !== "SSE" && ENDPOINTS[k].method !== "WS");
    for (const key of planned) {
      const e = await call(key, { params: { projectId: "p", taskId: "t", jobId: "j", changeSetId: "c", sessionId: "s", screenId: "x" } }).catch((x) => x);
      expect(e, key).toMatchObject({ code: "not_implemented" });
    }
    const live = (Object.keys(ENDPOINTS) as EndpointKey[]).filter((k) => ENDPOINTS[k].status === "live" && ENDPOINTS[k].method !== "SSE");
    for (const key of live) {
      calls.length = 0;
      const e = await call(key, { params: { projectId: "p", buildId: "b", jobId: "j", artifactId: "a", uploadId: "u", taskId: "t", changeSetId: "c" }, query: { path: "x", q: "y" }, body: {} }).catch((x) => x);
      expect((e as { code?: string } | undefined)?.code, `${key} is marked live but has no handler`).not.toBe("not_implemented");
    }
  });
});

describe("projects and files", () => {
  it("creates a project from the wizard without inventing an agent task", async () => {
    responders.push((c) => (c.method === "POST" && c.url === "/api/v1/projects"
      ? { status: 201, body: { id: "p1", name: "T", description: "d", source_type: "empty", status: "active", metadata: {}, storage_bytes: 0, active_jobs: 0, last_build: null, created_at: "t", updated_at: "t" } }
      : undefined));
    const out = await call<{ project: { id: string }; taskId: string | null }>("projects.createFromPrompt", {
      body: { name: "T", description: "d", requirements: ["offline"], language: "kotlin", uiToolkit: "compose", packageName: "com.x.y", minSdk: 26, targetSdk: 35, config: { K: "v" } },
    });
    expect(out.taskId).toBeNull();
    expect(calls[0]!.body).toEqual({
      name: "T", description: "d",
      metadata: { language: "kotlin", ui_toolkit: "compose", package_name: "com.x.y", min_sdk: 26, target_sdk: 35, requirements: ["offline"], config: { K: "v" } },
    });
  });

  it("saves with the version token as base_sha256 and maps conflicts", async () => {
    const path = "/api/v1/projects/p1/files/content";
    responders.push((c) => (c.method === "PUT" && c.url === `${path}?path=a.kt` ? { body: { sha256: "new" } } : undefined));
    const saved = await call<{ version: string; content: string }>("projects.files.save", { params: { projectId: "p1" }, query: { path: "a.kt" }, body: { content: "x", baseVersion: "old" } });
    expect(calls[0]!.body).toEqual({ content: "x", base_sha256: "old" });
    expect(saved).toMatchObject({ version: "new", content: "x", aiRanges: [] });
    responders.length = 0;
    responders.push(on("PUT", path, err("conflict"), 409));
    await expect(call("projects.files.save", { params: { projectId: "p1" }, query: { path: "a.kt" }, body: { content: "x", baseVersion: "old" } }))
      .rejects.toMatchObject({ status: 409, code: "file.version_conflict" });
  });

  it("creates directories as .keep markers and reports duplicates as file.exists", async () => {
    responders.push((c) => (c.method === "PUT" ? { body: { sha256: "h" } } : undefined));
    await call("projects.files.create", { params: { projectId: "p1" }, body: { path: "app/new", type: "dir" } });
    expect(calls[0]!.url).toBe("/api/v1/projects/p1/files/content?path=app%2Fnew%2F.keep");
    responders.length = 0;
    responders.push(on("PUT", "/api/v1/projects/p1/files/content", err("conflict"), 409));
    await expect(call("projects.files.create", { params: { projectId: "p1" }, body: { path: "a.kt", type: "file" } })).rejects.toMatchObject({ code: "file.exists" });
  });

  it("reads binary files as binary instead of failing", async () => {
    responders.push(on("GET", "/api/v1/projects/p1/files/content", err("binary_file"), 415));
    expect(await call("projects.files.read", { params: { projectId: "p1" }, query: { path: "logo.png" } })).toMatchObject({ binary: true, content: "" });
  });

  it("moves and deletes recursively through the backend", async () => {
    responders.push((c) => (c.method === "POST" || c.method === "DELETE" ? { status: 204 } : undefined));
    await call("projects.files.move", { params: { projectId: "p1" }, body: { from: "a", to: "b" } });
    await call("projects.files.delete", { params: { projectId: "p1" }, query: { path: "a/b" } });
    expect(calls[0]).toMatchObject({ method: "POST", url: "/api/v1/projects/p1/files/move", body: { from: "a", to: "b" } });
    expect(calls[1]).toMatchObject({ method: "DELETE" });
    expect(calls[1]!.url).toContain("recursive=true");
    expect(calls[1]!.url).toContain("path=a%2Fb");
  });

  it("filters the activity feed to meaningful events and honours the limit", async () => {
    const row = (id: string, action: string) => ({ id, project_id: "p", project_name: "A", action, detail: { number: 1 }, created_at: "t" });
    responders.push(on("GET", "/api/v1/projects/activity/recent", [row("1", "file.write"), row("2", "build.completed"), row("3", "build.failed"), row("4", "snapshot.create"), row("5", "project.create")]));
    const out = await call<{ id: string }[]>("projects.activity", { query: { limit: 2 } });
    expect(out.map((e) => e.id)).toEqual(["2", "3"]);
  });
});

describe("builds", () => {
  it("starts and retries builds with backend field names", async () => {
    const b = { id: "b1", project_id: "p1", number: 1, state: "queued", variant: "release", output_type: "aab", gradle_tasks: ["bundleRelease"], agent_run_id: null, commit_sha: "abc",
      artifact_ids: [], errors: [], duration_seconds: null, blocked_reason: null, error_message: null, queued_at: "t", started_at: null, finished_at: null, created_at: "t" };
    responders.push(on("POST", "/api/v1/builds", b, 201), on("GET", "/api/v1/builds/b0", b));
    await call("builds.start", { body: { projectId: "p1", variant: "release", outputType: "aab" } });
    expect(calls[0]!.body).toEqual({ project_id: "p1", variant: "release", output_type: "aab" });
    calls.length = 0;
    await call("builds.retry", { params: { buildId: "b0" } });
    expect(calls[1]).toMatchObject({ method: "POST", body: { project_id: "p1", variant: "release", output_type: "aab" } });
  });

  it("assembles paginated logs into one text with trailing newlines trimmed", async () => {
    const chunk = (n: number, start: number) => Array.from({ length: n }, (_, i) => ({ seq: start + i, stream: "stdout", content: `line ${start + i}\n` }));
    responders.push((c) => {
      if (!c.url.startsWith("/api/v1/builds/b1/logs")) return undefined;
      const after = Number(new URL(c.url, "http://x").searchParams.get("after_seq"));
      return { body: after < 0 ? chunk(1000, 0) : chunk(5, 1000) };
    });
    const text = await call<string>("builds.logs", { params: { buildId: "b1" } });
    expect(text.split("\n")).toHaveLength(1005);
    expect(text.endsWith("line 1004")).toBe(true);
    expect(calls).toHaveLength(2);
  });

  it("returns a download URL with an expiry", async () => {
    responders.push(on("POST", "/api/v1/artifacts/a1/download-url", { url: "/api/v1/artifacts/a1/content?exp=1&sig=2", expires_in: 300 }));
    const d = await call<{ url: string; expiresAt: string }>("artifacts.download", { params: { artifactId: "a1" } });
    expect(d.url).toContain("/content?");
    expect(Date.parse(d.expiresAt)).toBeGreaterThan(Date.now());
  });
});

describe("tests and admin", () => {
  it("starts instrumentation tests as 'instrumented' on the backend", async () => {
    responders.push(on("POST", "/api/v1/tests", { id: "t", project_id: "p", state: "blocked", kind: "instrumented", build_job_id: "b", agent_run_id: null, blocked_reason: "no KVM", emulator_profile: null, started_at: null, finished_at: null, result: null }, 201));
    const t = await call<{ kind: string; state: string; reason: string }>("tests.start", { body: { projectId: "p", kind: "instrumentation", buildId: "b" } });
    expect(calls[0]!.body).toEqual({ project_id: "p", kind: "instrumented", build_job_id: "b" });
    expect(t).toMatchObject({ kind: "instrumentation", state: "queued", reason: "no KVM" });
  });

  it("maps preferences both ways", async () => {
    responders.push((c) => (c.url === "/api/v1/users/me/preferences"
      ? { body: { theme: "dark", default_language: "java", default_ui_toolkit: "xml", email_build_failed: false, email_agent_task_completed: true, email_usage_threshold: true } }
      : undefined));
    const prefs = { theme: "dark", defaultLanguage: "java", defaultUiToolkit: "xml", emailNotifications: { buildFailed: false, agentTaskCompleted: true, usageThreshold: true } } as const;
    expect(await call("users.preferences")).toEqual(prefs);
    await call("users.updatePreferences", { body: prefs });
    expect(calls[1]!.body).toEqual({ theme: "dark", default_language: "java", default_ui_toolkit: "xml", email_build_failed: false, email_agent_task_completed: true, email_usage_threshold: true });
  });

  it("network failures are reported as unreachable", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => { throw new TypeError("failed to fetch"); }));
    const e = await call("projects.list").catch((x) => x);
    expect(e).toMatchObject({ code: "network", unreachable: true });
    expect(isPendingBackend(e)).toBe(true);
  });

  it("an unreachable backend (no error envelope, 502) is a waiting state, not a crash", async () => {
    responders.push(() => ({ status: 502, body: "<html>bad gateway</html>" }));
    const e = await call("projects.list").catch((x) => x);
    expect(isPendingBackend(e)).toBe(true);
  });
});

describe("agent (dev bridge)", () => {
  it("passes messages, tasks and change sets straight through", async () => {
    const message = { id: "m1", role: "user", content: "hi", createdAt: "2026-01-01T00:00:00Z" };
    const task = { id: "t1", projectId: "p1", status: "queued" };
    const changeSet = { id: "c1", taskId: "t1", summary: "s", status: "applied", files: [] };
    responders.push(on("GET", "/api/v1/agent/projects/p1/messages", [message]));
    responders.push(on("POST", "/api/v1/agent/projects/p1/messages", { message, task }, 201));
    responders.push(on("GET", "/api/v1/agent/tasks/t1", task));
    responders.push(on("POST", "/api/v1/agent/change-sets/c1/decision", changeSet));
    expect(await call("agent.messages.list", { params: { projectId: "p1" } })).toEqual([message]);
    const sent = await call("agent.messages.send", { params: { projectId: "p1" }, body: { prompt: "x", intent: "modify", context: {} } });
    expect(sent).toEqual({ message, task });
    expect(await call("agent.tasks.get", { params: { taskId: "t1" } })).toEqual(task);
    expect(await call("agent.changeSets.decide", { params: { changeSetId: "c1" }, body: { acceptPaths: ["a"] } })).toEqual(changeSet);
  });

  it("a backend without the bridge (404) still reads as 'waiting for backend'", async () => {
    responders.push((c) => (c.url.includes("/agent/") ? { status: 404, body: { detail: "Not Found" } } : undefined));
    const e = await call("agent.messages.list", { params: { projectId: "p1" } }).catch((x) => x);
    expect(isPendingBackend(e)).toBe(true);
  });
});
