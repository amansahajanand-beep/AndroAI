import { describe, expect, it } from "vitest";
import {
  buildStatus, buildTree, mapActivity, mapBuild, mapProject, mapTest, mapUser, mapWorker, page,
  type BBuild, type BProject, type BTest,
} from "./mappers";

const project = (over: Partial<BProject> = {}): BProject => ({
  id: "p1", name: "App", description: null, source_type: "zip", status: "active", metadata: {}, storage_bytes: 10,
  active_jobs: 0, last_build: null, created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-02T00:00:00Z", ...over,
});

const build = (over: Partial<BBuild> = {}): BBuild => ({
  id: "b1", project_id: "p1", number: 3, state: "completed", variant: "debug", output_type: "apk",
  gradle_tasks: ["assembleDebug"], agent_run_id: null, commit_sha: "abc1234", artifact_ids: ["a1"], errors: [],
  duration_seconds: 12.5, blocked_reason: null, error_message: null, queued_at: "2026-01-01T00:00:00Z",
  started_at: "2026-01-01T00:00:01Z", finished_at: "2026-01-01T00:00:13Z", created_at: "2026-01-01T00:00:00Z", ...over,
});

const test = (over: Partial<BTest> = {}): BTest => ({
  id: "t1", project_id: "p1", state: "completed", kind: "unit", build_job_id: null, agent_run_id: null,
  blocked_reason: null, error_message: null, emulator_profile: null, started_at: null, finished_at: "2026-01-01T00:00:00Z",
  result: { outcome: "passed", not_run_reason: null, passed: 3, failed: 0, skipped: 1, duration_seconds: 2 }, ...over,
});

describe("users", () => {
  it("derives name and role", () => {
    const u = mapUser({ id: "1", email: "ada@example.com", display_name: null, is_active: true, email_verified: true, roles: ["user", "admin"], created_at: "x" });
    expect(u).toMatchObject({ name: "ada", role: "admin", emailVerified: true, avatarUrl: null });
    expect(mapUser({ id: "1", email: "b@x.io", display_name: "Bea", is_active: true, email_verified: false, roles: ["user"], created_at: "x" })).toMatchObject({ name: "Bea", role: "user" });
  });
});

describe("projects", () => {
  it("maps source, metadata and last build", () => {
    const p = mapProject(project({ source_type: "apk", metadata: { language: "java", ui_toolkit: "xml", package_name: "a.b", min_sdk: 21 },
      last_build: { id: "b", number: 2, state: "failed", finished_at: "t" } }));
    expect(p).toMatchObject({ source: "apk", isApkAnalysis: true, language: "java", uiToolkit: "xml", packageName: "a.b", minSdk: 21, targetSdk: 35,
      lastBuild: { id: "b", status: "failed", finishedAt: "t" }, description: "" });
    expect(mapProject(project({ source_type: "empty" })).source).toBe("prompt");
    expect(mapProject(project({ source_type: "zip" })).source).toBe("android_zip");
  });
  it("paginates with a cursor only when more remain", () => {
    expect(page({ items: [1, 2], total: 5, limit: 2, offset: 0 }, (x) => x).nextCursor).toBe("2");
    expect(page({ items: [5], total: 5, limit: 2, offset: 4 }, (x) => x).nextCursor).toBeNull();
  });
});

describe("file tree", () => {
  const f = (path: string) => ({ path, size: 1, sha256: "h", is_binary: false, version: 1, updated_at: "x" });
  it("builds nested, sorted dirs-first and hides .keep markers", () => {
    const tree = buildTree([f("b.txt"), f("app/src/Main.kt"), f("app/build.gradle"), f("empty/.keep"), f("a.txt")]);
    expect(tree.map((n) => `${n.type}:${n.name}`)).toEqual(["dir:app", "dir:empty", "file:a.txt", "file:b.txt"]);
    const app = tree[0]!;
    expect(app.children!.map((n) => n.name)).toEqual(["src", "build.gradle"]);
    expect(app.children![0]!.children![0]).toMatchObject({ path: "app/src/Main.kt", type: "file" });
    expect(tree[1]!.children).toEqual([]);
  });
});

describe("builds", () => {
  it("maps backend states", () => {
    expect(["queued", "blocked", "starting", "running", "completed", "failed", "cancelled"].map(buildStatus)).toEqual(
      ["queued", "queued", "running", "running", "succeeded", "failed", "cancelled"]);
  });
  it("maps a finished build", () => {
    expect(mapBuild(build())).toMatchObject({ number: 3, status: "succeeded", gradleTask: "assembleDebug", durationMs: 12500,
      triggeredBy: "user", artifactIds: ["a1"], commitSha: "abc1234", errorSummary: null });
  });
  it("explains why a queued build is waiting", () => {
    const b = mapBuild(build({ state: "blocked", blocked_reason: "no live build worker is registered", duration_seconds: null, started_at: null, finished_at: null }));
    expect(b.status).toBe("queued");
    expect(b.errorSummary).toBe("no live build worker is registered");
    expect(b.durationMs).toBeNull();
  });
  it("converts extracted errors and summarises failures", () => {
    const b = mapBuild(build({ state: "failed", errors: [{ file: "A.kt", line: 3, message: "Unresolved reference" }, { path: "B.kt", severity: "warning", message: "w" }], agent_run_id: "run1" }));
    expect(b.errors[0]).toMatchObject({ path: "A.kt", line: 3, column: 1, severity: "error", message: "Unresolved reference" });
    expect(b.errors[1]).toMatchObject({ path: "B.kt", severity: "warning" });
    expect(b.errorSummary).toBe("Unresolved reference");
    expect(b.triggeredBy).toBe("agent");
  });
});

describe("tests", () => {
  it("passes only a real pass", () => {
    expect(mapTest(test())).toMatchObject({ state: "finished", result: "passed", kind: "unit", summary: { passed: 3, skipped: 1, blocked: 0 } });
  });
  it("never reports an unrun test as passed", () => {
    const t = mapTest(test({ kind: "emulator", result: { outcome: "not_run", not_run_reason: "KVM missing", passed: 0, failed: 0, skipped: 0, duration_seconds: null } }));
    expect(t.result).toBe("blocked");
    expect(t.summary.blocked).toBe(1);
    expect(t.reason).toBe("KVM missing");
  });
  it("maps lifecycle and kinds", () => {
    expect(mapTest(test({ state: "blocked", result: null, blocked_reason: "no emulator worker", finished_at: null })))
      .toMatchObject({ state: "queued", result: null, reason: "no emulator worker" });
    expect(mapTest(test({ state: "running", result: null, finished_at: null })).state).toBe("running");
    expect(mapTest(test({ kind: "instrumented" })).kind).toBe("instrumentation");
    expect(mapTest(test({ state: "cancelled" })).result).toBeNull();
    expect(mapTest(test({ result: { outcome: "error", not_run_reason: null, passed: 0, failed: 0, skipped: 0, duration_seconds: 1 }, state: "failed" })).result).toBe("failed");
  });
});

describe("activity and workers", () => {
  const a = (action: string, detail = {}) => mapActivity({ id: "1", project_id: "p", project_name: "App", action, detail, created_at: "t" });
  it("keeps meaningful events and drops noise", () => {
    expect(a("project.create")?.kind).toBe("project_created");
    expect(a("build.completed", { number: 4 })).toMatchObject({ kind: "build_succeeded", message: "Build #4 succeeded" });
    expect(a("build.failed", { number: 5 })?.kind).toBe("build_failed");
    expect(a("test.finished", { outcome: "passed" })?.kind).toBe("tests_passed");
    expect(a("test.finished", { outcome: "not_run" })?.kind).toBe("tests_failed");
    expect(a("upload.zip")?.kind).toBe("files_changed");
    for (const noise of ["file.write", "file.delete", "snapshot.create", "build.submit", "upload.rejected", "project.update"]) expect(a(noise)).toBeNull();
  });
  it("reports silent workers as offline", () => {
    const w = (over = {}) => mapWorker({ id: "i", name: "build-1", kind: "build", status: "idle", live: true, last_heartbeat_at: "t", ...over });
    expect(w().state).toBe("idle");
    expect(w({ live: false }).state).toBe("offline");
    expect(w({ status: "busy" }).state).toBe("busy");
    expect(w({ status: "draining" }).state).toBe("draining");
    expect(w({ kind: "emulator" }).pool).toBe("emulator");
  });
});
