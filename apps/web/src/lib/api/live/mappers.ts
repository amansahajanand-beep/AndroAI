/**
 * Backend (snake_case, docs/API.md) -> frontend contract (camelCase, @apppilot/contracts).
 * Pure functions: no I/O, covered by unit tests.
 */
import type {
  ActivityEvent,
  AdminAuditEvent,
  AdminOverview,
  AdminUser,
  Artifact,
  Build,
  BuildStatus,
  FileNode,
  Paginated,
  Project,
  TestJob,
  TestJobKind,
  User,
  UserPreferences,
  WorkerStatus,
} from "@apppilot/contracts";

/* ---- backend shapes (only the fields we read) ---- */
export interface BUser {
  id: string;
  email: string;
  display_name: string | null;
  is_active: boolean;
  email_verified: boolean;
  roles: string[];
  created_at: string;
  last_login_at?: string | null;
  project_count?: number;
}
export interface BPage<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}
export interface BProject {
  id: string;
  name: string;
  description: string | null;
  source_type: string;
  status: string;
  metadata: Record<string, unknown>;
  storage_bytes: number;
  active_jobs: number;
  last_build: { id: string; number: number; state: string; finished_at: string | null } | null;
  created_at: string;
  updated_at: string;
}
export interface BFile {
  path: string;
  size: number;
  sha256: string;
  is_binary: boolean;
  version: number;
  updated_at: string;
}
export interface BBuild {
  id: string;
  project_id: string;
  number: number;
  state: string;
  variant: "debug" | "release";
  output_type: "apk" | "aab";
  gradle_tasks: string[];
  agent_run_id: string | null;
  commit_sha: string;
  artifact_ids: string[];
  errors: { file?: string; path?: string; line?: number; column?: number; message?: string; severity?: string; task?: string }[];
  duration_seconds: number | null;
  blocked_reason: string | null;
  error_message: string | null;
  queued_at: string | null;
  started_at: string | null;
  finished_at: string | null;
  created_at: string;
}
export interface BTest {
  id: string;
  project_id: string;
  state: string;
  kind: string;
  build_job_id: string | null;
  agent_run_id: string | null;
  blocked_reason: string | null;
  error_message: string | null;
  emulator_profile: { name?: string; device?: string; api_level?: number; abi?: string } | null;
  started_at: string | null;
  finished_at: string | null;
  result: {
    outcome: "passed" | "failed" | "not_run" | "error";
    not_run_reason: string | null;
    passed: number;
    failed: number;
    skipped: number;
    duration_seconds: number | null;
  } | null;
}
export interface BArtifact {
  id: string;
  project_id: string;
  kind: string;
  name: string;
  size: number;
  sha256: string;
  build_job_id: string | null;
  created_at: string;
  expires_at: string | null;
}

/* ---- helpers ---- */
export const page = <B, F>(p: BPage<B>, map: (b: B) => F): Paginated<F> => ({
  items: p.items.map(map),
  total: p.total,
  nextCursor: p.offset + p.items.length < p.total ? String(p.offset + p.items.length) : null,
});

const str = (v: unknown): string | undefined => (typeof v === "string" ? v : undefined);
const num = (v: unknown): number | undefined => (typeof v === "number" ? v : undefined);

/* ---- users ---- */
export const mapUser = (u: BUser): User => ({
  id: u.id,
  name: u.display_name || u.email.split("@")[0] || u.email,
  email: u.email,
  avatarUrl: null,
  role: u.roles.includes("admin") ? "admin" : "user",
  emailVerified: u.email_verified,
  createdAt: u.created_at,
});

export const mapAdminUser = (u: BUser): AdminUser => ({
  ...mapUser(u),
  planId: "—", // billing is not connected yet
  status: u.is_active ? "active" : "suspended",
  projectCount: u.project_count ?? 0,
  lastActiveAt: u.last_login_at ?? null,
});

interface BPrefs {
  theme: UserPreferences["theme"];
  default_language: UserPreferences["defaultLanguage"];
  default_ui_toolkit: UserPreferences["defaultUiToolkit"];
  email_build_failed: boolean;
  email_agent_task_completed: boolean;
  email_usage_threshold: boolean;
}
export const mapPrefs = (p: BPrefs): UserPreferences => ({
  theme: p.theme,
  defaultLanguage: p.default_language,
  defaultUiToolkit: p.default_ui_toolkit,
  emailNotifications: {
    buildFailed: p.email_build_failed,
    agentTaskCompleted: p.email_agent_task_completed,
    usageThreshold: p.email_usage_threshold,
  },
});
export const prefsToBackend = (p: UserPreferences): BPrefs => ({
  theme: p.theme,
  default_language: p.defaultLanguage,
  default_ui_toolkit: p.defaultUiToolkit,
  email_build_failed: p.emailNotifications.buildFailed,
  email_agent_task_completed: p.emailNotifications.agentTaskCompleted,
  email_usage_threshold: p.emailNotifications.usageThreshold,
});

/* ---- builds ---- */
export function buildStatus(state: string): BuildStatus {
  switch (state) {
    case "completed":
      return "succeeded";
    case "failed":
    case "cancelled":
      return state;
    case "starting":
    case "running":
      return "running";
    default:
      return "queued"; // queued | blocked
  }
}

/* ---- projects ---- */
export function mapProject(p: BProject): Project {
  const m = p.metadata ?? {};
  const lb = p.last_build;
  return {
    id: p.id,
    name: p.name,
    description: p.description ?? "",
    source: p.source_type === "apk" ? "apk" : p.source_type === "zip" ? "android_zip" : "prompt",
    status: "ready", // there is no agent generation phase yet; archived projects are hidden from lists
    language: m.language === "java" ? "java" : "kotlin",
    uiToolkit: m.ui_toolkit === "xml" ? "xml" : "compose",
    packageName: str(m.package_name) ?? null,
    minSdk: num(m.min_sdk) ?? 24,
    targetSdk: num(m.target_sdk) ?? 35,
    isApkAnalysis: p.source_type === "apk",
    activeTaskCount: 0, // agent tasks: not connected yet
    lastBuild: lb ? { id: lb.id, status: buildStatus(lb.state), finishedAt: lb.finished_at } : null,
    storageBytes: p.storage_bytes,
    createdAt: p.created_at,
    updatedAt: p.updated_at,
  };
}

/** The backend stores a flat file list; directories exist implicitly (and as `.keep` markers). */
export function buildTree(files: BFile[]): FileNode[] {
  const root: FileNode = { path: "", name: "", type: "dir", children: [] };
  const dirs = new Map<string, FileNode>([["", root]]);
  const ensureDir = (path: string): FileNode => {
    const existing = dirs.get(path);
    if (existing) return existing;
    const parentPath = path.includes("/") ? path.slice(0, path.lastIndexOf("/")) : "";
    const node: FileNode = { path, name: path.slice(path.lastIndexOf("/") + 1), type: "dir", children: [] };
    ensureDir(parentPath).children!.push(node);
    dirs.set(path, node);
    return node;
  };
  for (const f of files) {
    if (f.path.endsWith("/.keep")) {
      ensureDir(f.path.slice(0, -"/.keep".length));
      continue;
    }
    const parent = f.path.includes("/") ? f.path.slice(0, f.path.lastIndexOf("/")) : "";
    ensureDir(parent).children!.push({
      path: f.path,
      name: f.path.slice(f.path.lastIndexOf("/") + 1),
      type: "file",
      sizeBytes: f.size,
      gitStatus: null,
      aiModified: false,
    });
  }
  const sort = (n: FileNode) => {
    n.children?.sort((a, b) => (a.type === b.type ? a.name.localeCompare(b.name) : a.type === "dir" ? -1 : 1));
    n.children?.forEach(sort);
  };
  sort(root);
  return root.children ?? [];
}

export function mapBuild(b: BBuild): Build {
  const started = b.started_at ? Date.parse(b.started_at) : null;
  const finished = b.finished_at ? Date.parse(b.finished_at) : null;
  const errors = b.errors.map((e) => ({
    path: e.path ?? e.file ?? "",
    line: e.line ?? 1,
    column: e.column ?? 1,
    severity: (e.severity === "warning" ? "warning" : "error") as "error" | "warning",
    message: e.message ?? "",
    task: e.task ?? "",
  }));
  const status = buildStatus(b.state);
  return {
    id: b.id,
    projectId: b.project_id,
    number: b.number,
    outputType: b.output_type,
    variant: b.variant,
    status,
    gradleTask: b.gradle_tasks.join(" "),
    commitSha: b.commit_sha,
    triggeredBy: b.agent_run_id ? "agent" : "user",
    agentTaskId: b.agent_run_id,
    queuedAt: b.queued_at ?? b.created_at,
    startedAt: b.started_at,
    finishedAt: b.finished_at,
    durationMs: b.duration_seconds != null ? Math.round(b.duration_seconds * 1000) : started && finished ? finished - started : null,
    // A blocked job shows why it is waiting (e.g. "no live build worker is registered").
    errorSummary: b.error_message ?? (status === "queued" ? b.blocked_reason : null) ?? errors[0]?.message ?? null,
    errors,
    artifactIds: b.artifact_ids,
  };
}

/* ---- tests ---- */
const TEST_KIND: Record<string, TestJobKind> = { unit: "unit", emulator: "emulator", instrumented: "instrumentation" };

export function mapTest(t: BTest): TestJob {
  const r = t.result;
  const finished = ["completed", "failed", "cancelled"].includes(t.state);
  const queued = t.state === "queued" || t.state === "blocked";
  // not_run (no emulator/KVM, build missing...) is reported as "blocked": never as a pass.
  const result: TestJob["result"] =
    !finished || t.state === "cancelled" || !r
      ? null
      : r.outcome === "passed"
        ? "passed"
        : r.outcome === "not_run"
          ? "blocked"
          : "failed";
  const p = t.emulator_profile;
  return {
    id: t.id,
    projectId: t.project_id,
    buildId: t.build_job_id,
    kind: TEST_KIND[t.kind] ?? "unit",
    state: queued ? "queued" : finished ? "finished" : "running",
    result,
    summary: {
      passed: r?.passed ?? 0,
      failed: r?.failed ?? 0,
      blocked: r?.outcome === "not_run" ? 1 : 0,
      unverified: 0,
      skipped: r?.skipped ?? 0,
    },
    device: p ? { name: p.name ?? p.device ?? "Emulator", apiLevel: p.api_level ?? 0, abi: p.abi ?? "x86_64" } : null,
    startedAt: t.started_at,
    finishedAt: t.finished_at,
    durationMs: r?.duration_seconds != null ? Math.round(r.duration_seconds * 1000) : null,
    triggeredBy: t.agent_run_id ? "agent" : "user",
    reason: r?.not_run_reason ?? t.blocked_reason ?? t.error_message,
  };
}

export const mapArtifact = (a: BArtifact): Artifact => ({
  id: a.id,
  projectId: a.project_id,
  buildId: a.build_job_id,
  kind: (["apk", "aab", "log", "report", "upload"].includes(a.kind) ? a.kind : "report") as Artifact["kind"],
  fileName: a.name,
  sizeBytes: a.size,
  sha256: a.sha256,
  createdAt: a.created_at,
  expiresAt: a.expires_at,
});

/* ---- activity ---- */
export interface BActivity {
  id: string;
  project_id: string;
  project_name: string;
  action: string;
  detail: Record<string, unknown>;
  created_at: string;
}
/** Returns null for actions that are too low-level to show in the feed. */
export function mapActivity(a: BActivity): ActivityEvent | null {
  const base = { id: a.id, projectId: a.project_id, projectName: a.project_name, at: a.created_at };
  const n = num(a.detail.number);
  switch (a.action) {
    case "project.create":
      return { ...base, kind: "project_created", message: "Project created" };
    case "upload.zip":
    case "upload.apk":
      return { ...base, kind: "files_changed", message: a.action === "upload.apk" ? "APK uploaded" : "Project files uploaded" };
    case "build.completed":
      return { ...base, kind: "build_succeeded", message: `Build #${n ?? "?"} succeeded` };
    case "build.failed":
      return { ...base, kind: "build_failed", message: `Build #${n ?? "?"} failed` };
    case "test.finished": {
      const ok = a.detail.outcome === "passed";
      return { ...base, kind: ok ? "tests_passed" : "tests_failed", message: ok ? "Tests passed" : `Tests did not pass (${String(a.detail.outcome)})` };
    }
    default:
      return null;
  }
}

/* ---- admin ---- */
export interface BWorker {
  id: string;
  name: string;
  kind: string;
  status: string;
  live: boolean;
  last_heartbeat_at: string | null;
}
export const mapWorker = (w: BWorker): WorkerStatus => ({
  id: w.name,
  pool: w.kind === "emulator" ? "emulator" : w.kind === "test" ? "test" : "build",
  state: !w.live || w.status === "offline" || w.status === "unhealthy" ? "offline" : w.status === "draining" ? "draining" : w.status === "busy" ? "busy" : "idle",
  currentJobId: null,
  lastHeartbeatAt: w.last_heartbeat_at,
});

export interface BAudit {
  id: string;
  actor_id: string | null;
  actor_email: string | null;
  action: string;
  resource_type: string | null;
  resource_id: string | null;
  created_at: string;
}
export const mapAudit = (a: BAudit): AdminAuditEvent => ({
  id: a.id,
  actorEmail: a.actor_email ?? a.actor_id ?? "system",
  action: a.action,
  target: [a.resource_type, a.resource_id].filter(Boolean).join(":"),
  at: a.created_at,
});

export interface BOverview {
  users: number;
  active_users_7d: number;
  projects: number;
  builds_today: number;
  build_failure_rate_24h: number;
  queue_depth: Record<string, number>;
  ai_cost_today_usd: number;
}
export const mapOverview = (o: BOverview): AdminOverview => ({
  users: o.users,
  activeUsers7d: o.active_users_7d,
  projects: o.projects,
  buildsToday: o.builds_today,
  buildFailureRate24h: o.build_failure_rate_24h,
  agentTasksRunning: 0, // agent API not connected yet
  queueDepth: { builds: o.queue_depth.builds ?? 0, agent: 0, tests: o.queue_depth.tests ?? 0 },
  aiCostTodayUsd: o.ai_cost_today_usd,
});
