/**
 * DEV-ONLY mock transport. Loaded only when NEXT_PUBLIC_API_MODE=mock.
 * Endpoints without a handler respond 501 so screens show their
 * "waiting for backend" state — the same thing users would see live.
 */
import type {
  AgentTask,
  AgentTaskStatus,
  AgentTimelineEvent,
  Build,
  ChangeSet,
  ChangeSetDecisionRequest,
  ChatMessage,
  CreateFileRequest,
  CreateProjectFromPromptRequest,
  CreateUploadRequest,
  EndpointKey,
  FileNode,
  LoginRequest,
  MoveFileRequest,
  Project,
  ProjectEnvVar,
  RegisterRequest,
  SaveFileRequest,
  SendAgentMessageRequest,
  StartBuildRequest,
  StartTestJobRequest,
  TestJob,
  UpdateProfileRequest,
  UpdateProjectRequest,
  UploadSession,
  UsageDailyPoint,
  UserPreferences,
} from "@apppilot/contracts";
import { ApiError } from "../errors";
import { resolvePath, type ResolvedRequest, type Transport } from "../transport";
import { mockBus } from "./bus";
import { ago, db, nextVersion, type MockFile } from "./db";
import {
  consumeResetToken,
  createDemoUser,
  createResetTokenIfAccountExists,
  EmailTakenError,
  startSession,
  clearSession,
  toSessionUser,
  updateDemoUser,
  verifyCredentials,
  type DemoUser,
} from "./demo-auth-store";
import { SAMPLE_CHANGE } from "./sample-project";

type Handler = (req: ResolvedRequest) => unknown;

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
const now = () => new Date().toISOString();
let idSeq = 100;
const newId = (prefix: string) => `${prefix}_${idSeq++}`;

const fail = (status: number, code: string, message: string, fields?: Record<string, string>): never => {
  throw new ApiError({ status, code, message, fields });
};
const notFound = (what: string) => fail(404, "not_found", `${what} not found.`);
const requireAuth = () => {
  if (!db.signedIn) fail(401, "auth.required", "Sign in to continue.");
};

/* ---------------- helpers ---------------- */

function projectFiles(projectId: string) {
  const files = db.files.get(projectId);
  if (!files) return notFound("Project");
  return files;
}

function buildTree(files: Map<string, MockFile>): FileNode[] {
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
  for (const [path, f] of files) {
    if (path.endsWith("/.keep")) {
      ensureDir(path.slice(0, -"/.keep".length));
      continue;
    }
    const parentPath = path.includes("/") ? path.slice(0, path.lastIndexOf("/")) : "";
    ensureDir(parentPath).children!.push({
      path,
      name: path.slice(path.lastIndexOf("/") + 1),
      type: "file",
      sizeBytes: f.content.length,
      gitStatus: f.gitStatus,
      aiModified: f.aiModified,
    });
  }
  const sort = (n: FileNode) => {
    n.children?.sort((a, b) => (a.type === b.type ? a.name.localeCompare(b.name) : a.type === "dir" ? -1 : 1));
    n.children?.forEach(sort);
  };
  sort(root);
  return root.children ?? [];
}

const projectEvents = (projectId: string) => resolvePath("projects.events", { projectId });
const taskEvents = (taskId: string) => resolvePath("agent.tasks.events", { taskId });
const buildLogStream = (buildId: string) => resolvePath("builds.logs.stream", { buildId });

/* ---------------- simulations (dev only) ---------------- */

const runningBuildSims = new Set<string>();

function simulateBuild(b: Build) {
  if (runningBuildSims.has(b.id) || b.status !== "running") return;
  runningBuildSims.add(b.id);
  const lines = [
    `> Configure project :app`,
    `> Task :app:preBuild UP-TO-DATE`,
    `> Task :app:generate${b.variant === "release" ? "Release" : "Debug"}Resources`,
    `> Task :app:compile${b.variant === "release" ? "Release" : "Debug"}Kotlin`,
    `> Task :app:compile${b.variant === "release" ? "Release" : "Debug"}JavaWithJavac`,
    ...(b.variant === "release" ? ["> Task :app:minifyReleaseWithR8", "R8: applying keep rules from proguard-rules.pro"] : []),
    `> Task :app:package${b.variant === "release" ? "Release" : "Debug"}`,
    `> Task ${b.gradleTask}`,
    ``,
    `BUILD SUCCESSFUL in ${b.variant === "release" ? "2m 41s" : "1m 12s"}`,
  ];
  const log = db.buildLogs.get(b.id) ?? [`$ ./gradlew ${b.gradleTask} --console=plain`];
  db.buildLogs.set(b.id, log);
  let i = 0;
  const t = setInterval(() => {
    const line = lines[i++];
    if (line === undefined) {
      clearInterval(t);
      b.status = "succeeded";
      b.finishedAt = now();
      b.durationMs = Date.now() - new Date(b.startedAt ?? now()).getTime();
      const p = db.projects.find((x) => x.id === b.projectId);
      if (p) p.lastBuild = { id: b.id, status: "succeeded", finishedAt: b.finishedAt };
      mockBus.emit(buildLogStream(b.id), "end", { status: b.status });
      mockBus.emit(projectEvents(b.projectId), "build.updated", { type: "build.updated", buildId: b.id, status: b.status });
      runningBuildSims.delete(b.id);
      return;
    }
    log.push(line);
    mockBus.emit(buildLogStream(b.id), "log", { seq: log.length, line });
  }, 700);
}

const AGENT_FLOW: { status: AgentTaskStatus; title: string; step: string }[] = [
  { status: "planning", title: "Planning the change", step: "Reading the request and open files" },
  { status: "analyzing", title: "Analyzing affected files", step: "Reading related source files" },
  { status: "generating", title: "Writing changes", step: "Generating proposed edits" },
  { status: "reviewing", title: "Self-review", step: "Checking edits against the plan" },
  { status: "building", title: "Debug build", step: "Running :app:assembleDebug" },
  { status: "completed", title: "Changes ready for review", step: "" },
];

function simulateAgentTask(task: AgentTask, assistantMessage: ChatMessage) {
  let i = 0;
  const tick = () => {
    const stage = AGENT_FLOW[i++];
    if (!stage) return;
    task.status = stage.status;
    task.currentStep = stage.step || null;
    task.tokenUsage.inputTokens += 4000 + i * 900;
    task.tokenUsage.outputTokens += 600 + i * 300;
    task.recordedCostUsd = +(task.recordedCostUsd + 0.03).toFixed(2);
    task.filesAnalyzing = stage.status === "analyzing" ? [SAMPLE_CHANGE.modifiedPath] : [];
    task.filesModifying = stage.status === "generating" ? [SAMPLE_CHANGE.modifiedPath] : [];
    task.buildProgress = stage.status === "building" ? { percent: 55, phase: ":app:compileDebugKotlin" } : null;
    const ev: AgentTimelineEvent = { id: newId("ev"), taskId: task.id, at: now(), status: stage.status, title: stage.title };
    (db.timelines[task.id] ??= []).push(ev);
    mockBus.emit(taskEvents(task.id), "timeline.appended", { type: "timeline.appended", event: ev });

    if (stage.status === "completed") {
      task.finishedAt = now();
      const cs = makeChangeSet(task);
      assistantMessage.content = "(Mock response) I prepared a change for review. Nothing is applied until you accept it.";
      assistantMessage.changeSetId = cs?.id;
      mockBus.emit(taskEvents(task.id), "message.completed", { type: "message.completed", message: assistantMessage });
      if (cs) mockBus.emit(taskEvents(task.id), "changeset.ready", { type: "changeset.ready", changeSet: cs });
    }
    mockBus.emit(taskEvents(task.id), "task.updated", { type: "task.updated", task: { ...task } });
    mockBus.emit(projectEvents(task.projectId), "task.updated", { type: "task.updated", taskId: task.id, status: task.status });
    if (stage.status !== "completed") setTimeout(tick, 1400);
  };
  setTimeout(tick, 500);
}

function makeChangeSet(task: AgentTask): ChangeSet | null {
  const files = db.files.get(task.projectId);
  if (!files) return null;
  const target = files.get(SAMPLE_CHANGE.modifiedPath);
  const readme = files.get("README.md");
  const cs: ChangeSet = {
    id: newId("cs"),
    taskId: task.id,
    summary: target ? "Adds a search field that filters the trail list." : "Documents the request in README.md.",
    status: "pending",
    files: target
      ? [
          { path: SAMPLE_CHANGE.modifiedPath, changeType: "modify", originalContent: target.content, proposedContent: SAMPLE_CHANGE.modify(target.content), decision: "pending" },
          ...(files.has(SAMPLE_CHANGE.addedPath)
            ? []
            : [{ path: SAMPLE_CHANGE.addedPath, changeType: "add" as const, originalContent: null, proposedContent: SAMPLE_CHANGE.addedContent, decision: "pending" as const }]),
        ]
      : [
          {
            path: "README.md",
            changeType: readme ? "modify" : "add",
            originalContent: readme?.content ?? null,
            proposedContent: `${readme?.content ?? "# Project\n"}\n## Notes\n\n- ${task.description}\n`,
            decision: "pending",
          },
        ],
  };
  db.changeSets.push(cs);
  return cs;
}

function changedLineRange(before: string, after: string) {
  const a = before.split("\n");
  const b = after.split("\n");
  let start = 0;
  while (start < a.length && start < b.length && a[start] === b[start]) start++;
  let endA = a.length - 1;
  let endB = b.length - 1;
  while (endA >= start && endB >= start && a[endA] === b[endB]) {
    endA--;
    endB--;
  }
  return { startLine: start + 1, endLine: Math.max(start + 1, endB + 1) };
}

/* ---------------- handlers ---------------- */

const handlers: Partial<Record<EndpointKey, Handler>> = {
  // auth
  "auth.session": () => {
    requireAuth();
    return { user: db.user, expiresAt: new Date(Date.now() + 86_400_000).toISOString() };
  },
  "auth.login": (r) => {
    const b = r.body as LoginRequest;
    const demoUser =
      verifyCredentials(b.email, b.password) ?? fail(401, "auth.invalid_credentials", "That email and password don't match an account.");
    const { expiresAt } = startSession(demoUser.id, b.remember ?? true);
    db.signedIn = true;
    db.user = toSessionUser(demoUser);
    return { user: db.user, expiresAt };
  },
  "auth.register": (r) => {
    const b = r.body as RegisterRequest;
    let demoUser: DemoUser;
    try {
      demoUser = createDemoUser({ name: b.name, email: b.email, password: b.password });
    } catch (e) {
      if (e instanceof EmailTakenError) {
        return fail(409, "auth.email_taken", "An account with this email already exists.", { email: "This email is already registered." });
      }
      throw e;
    }
    const { expiresAt } = startSession(demoUser.id, true);
    db.signedIn = true;
    db.user = toSessionUser(demoUser);
    return { user: db.user, expiresAt };
  },
  "auth.logout": () => {
    clearSession();
    db.signedIn = false;
  },
  "auth.forgotPassword": (r) => {
    createResetTokenIfAccountExists((r.body as { email: string }).email);
    return { accepted: true };
  },
  "auth.resetPassword": (r) => {
    const b = r.body as { token: string; password: string };
    if (b.token === "expired") fail(400, "auth.reset_token_invalid", "This reset link has expired. Request a new one.");
    if (!consumeResetToken(b.token, b.password)) {
      fail(400, "auth.reset_token_invalid", "This reset link is invalid or has expired. Request a new one.");
    }
  },

  // users
  "users.me": () => (requireAuth(), db.user),
  "users.updateMe": (r) => {
    requireAuth();
    const patch = r.body as UpdateProfileRequest;
    db.user = { ...db.user, ...patch };
    updateDemoUser(db.user.id, patch);
    return db.user;
  },
  "users.changePassword": () => undefined,
  "users.preferences": () => db.prefs,
  "users.updatePreferences": (r) => (db.prefs = r.body as UserPreferences),
  "users.apiKeys": () => [
    { id: "k1", name: "CI pipeline", lastFour: "9f2c", createdAt: ago(60 * 24 * 20), lastUsedAt: ago(60 * 3) },
  ],

  // projects
  "projects.list": () => (requireAuth(), { items: db.projects, nextCursor: null, total: db.projects.length }),
  "projects.get": (r) => db.projects.find((p) => p.id === r.params.projectId) ?? notFound("Project"),
  "projects.createFromPrompt": (r) => {
    const b = r.body as CreateProjectFromPromptRequest;
    const id = newId("p");
    const project: Project = {
      id,
      name: b.name,
      description: b.description,
      source: "prompt",
      status: "creating",
      language: b.language,
      uiToolkit: b.uiToolkit,
      packageName: b.packageName ?? null,
      minSdk: b.minSdk ?? 26,
      targetSdk: b.targetSdk ?? 35,
      isApkAnalysis: false,
      activeTaskCount: 1,
      lastBuild: null,
      storageBytes: 0,
      createdAt: now(),
      updatedAt: now(),
    };
    db.projects.unshift(project);
    db.files.set(id, new Map([["README.md", { content: `# ${b.name}\n\n${b.description}\n`, version: nextVersion(), gitStatus: "added", aiModified: true, aiRanges: [] }]]));
    const task: AgentTask = {
      id: newId("t"), projectId: id, title: `Generate ${b.name}`, description: b.description, intent: "generate",
      status: "queued", currentStep: null, filesAnalyzing: [], filesModifying: [], buildProgress: null,
      repairIterations: 0, maxRepairIterations: 5, tokenUsage: { inputTokens: 0, outputTokens: 0 }, recordedCostUsd: 0,
      blockedReason: null, errorMessage: null, createdAt: now(), startedAt: now(), finishedAt: null,
    };
    db.tasks.unshift(task);
    db.timelines[task.id] = [{ id: newId("ev"), taskId: task.id, at: now(), status: "queued", title: "Task queued" }];
    const msg: ChatMessage = { id: newId("m"), role: "assistant", content: "", createdAt: now(), taskId: task.id };
    simulateAgentTask(task, msg);
    return { project, taskId: task.id };
  },
  "projects.update": (r) => {
    const p = db.projects.find((x) => x.id === r.params.projectId) ?? notFound("Project");
    Object.assign(p, r.body as UpdateProjectRequest, { updatedAt: now() });
    return p;
  },
  "projects.delete": (r) => {
    db.projects = db.projects.filter((p) => p.id !== r.params.projectId);
  },
  "projects.activity": () => db.activity,
  "projects.envVars": (r) => db.envVars[r.params.projectId!] ?? [],
  "projects.updateEnvVars": (r) => {
    const next = (r.body as ProjectEnvVar[]).map((v) => (v.secret ? { ...v, value: null } : v));
    db.envVars[r.params.projectId!] = next;
    return next;
  },
  "projects.uploads.create": (r) => {
    const b = r.body as CreateUploadRequest;
    const u: UploadSession = {
      id: newId("up"), kind: b.kind, status: "uploading", uploadUrl: "mock://upload",
      analysisProgress: 0, validationErrors: [], projectId: null, zipAnalysis: null, apkAnalysis: null,
    };
    (u as UploadSession & { fileName: string }).fileName = b.fileName;
    db.uploads.set(u.id, u);
    return u;
  },
  "projects.uploads.complete": (r) => {
    const u = db.uploads.get(r.params.uploadId!) ?? notFound("Upload");
    u.status = "validating";
    const started = Date.now();
    (u as UploadSession & { startedAt: number }).startedAt = started;
    return u;
  },
  "projects.uploads.get": (r) => {
    const u = db.uploads.get(r.params.uploadId!) ?? notFound("Upload");
    const elapsed = Date.now() - ((u as UploadSession & { startedAt?: number }).startedAt ?? Date.now());
    const fileName = (u as UploadSession & { fileName?: string }).fileName ?? "upload";
    if (fileName.includes("invalid")) {
      u.status = "failed";
      u.validationErrors = ["No settings.gradle or settings.gradle.kts found at the archive root or one level down.", "No AndroidManifest.xml found in any module."];
      return u;
    }
    if (elapsed < 1500) u.status = "validating";
    else if (elapsed < 6000) {
      u.status = "analyzing";
      u.analysisProgress = Math.min(99, Math.round(((elapsed - 1500) / 4500) * 100));
    } else if (u.status !== "ready") {
      u.status = "ready";
      u.analysisProgress = 100;
      const id = newId("p");
      const isApk = u.kind === "apk";
      const name = fileName.replace(/\.(zip|apk)$/i, "");
      db.projects.unshift({
        id, name: isApk ? `${name} (APK)` : name, description: isApk ? `Analysis of ${fileName}.` : `Imported from ${fileName}.`,
        source: isApk ? "apk" : "android_zip", status: "ready", language: "kotlin", uiToolkit: isApk ? "xml" : "compose",
        packageName: isApk ? "com.example.uploaded" : "com.example.imported", minSdk: 24, targetSdk: 34, isApkAnalysis: isApk,
        activeTaskCount: 0, lastBuild: null, storageBytes: 30_000_000, createdAt: now(), updatedAt: now(),
      });
      db.files.set(id, new Map([["README.md", { content: `# ${name}\n`, version: nextVersion(), gitStatus: null, aiModified: false, aiRanges: [] }]]));
      u.projectId = id;
      if (isApk) {
        u.apkAnalysis = {
          packageName: "com.example.uploaded", versionName: "2.4.1", versionCode: 241, minSdk: 23, targetSdk: 33, sizeBytes: 18_400_000,
          permissions: ["android.permission.INTERNET", "android.permission.ACCESS_COARSE_LOCATION", "android.permission.POST_NOTIFICATIONS"],
          activities: ["com.example.uploaded.MainActivity", "com.example.uploaded.settings.SettingsActivity"],
          services: ["com.example.uploaded.sync.SyncService"], receivers: ["com.example.uploaded.BootReceiver"],
          nativeAbis: ["arm64-v8a", "armeabi-v7a"], detectedLibraries: ["OkHttp 4.x", "Retrofit 2.x", "Firebase Analytics"], obfuscated: true,
          findings: [
            { severity: "info", message: "Code is obfuscated with R8; class and method names are not original." },
            { severity: "warning", message: "targetSdk 33 is below the current Play Store requirement." },
            { severity: "risk", message: "Cleartext HTTP traffic is permitted by the network security config." },
          ],
        };
      } else {
        u.zipAnalysis = {
          gradleWrapper: true, buildSystem: "gradle-kts", modules: [":app", ":core:data", ":feature:home"], language: "kotlin", uiToolkit: "compose",
          agpVersion: "8.5.0", kotlinVersion: "2.0.0", fileCount: 214, warnings: ["local.properties was included and will be ignored."],
        };
      }
    }
    return u;
  },

  // files
  "projects.files.tree": (r) => buildTree(projectFiles(r.params.projectId!)),
  "projects.files.read": (r) => {
    const path = String(r.query.path);
    const f = projectFiles(r.params.projectId!).get(path) ?? notFound("File");
    return { path, content: f.content, version: f.version, aiRanges: f.aiRanges };
  },
  "projects.files.save": (r) => {
    const path = String(r.query.path);
    const files = projectFiles(r.params.projectId!);
    const f = files.get(path) ?? notFound("File");
    const b = r.body as SaveFileRequest;
    if (b.baseVersion !== f.version) fail(409, "file.version_conflict", "This file changed since you opened it.");
    f.content = b.content;
    f.version = nextVersion();
    f.gitStatus = f.gitStatus === "added" ? "added" : "modified";
    f.aiModified = false;
    f.aiRanges = [];
    return { path, content: f.content, version: f.version, aiRanges: [] };
  },
  "projects.files.create": (r) => {
    const b = r.body as CreateFileRequest;
    const files = projectFiles(r.params.projectId!);
    const path = b.type === "dir" ? `${b.path}/.keep` : b.path;
    if (files.has(b.path) || files.has(path)) fail(409, "file.exists", `${b.path} already exists.`);
    files.set(path, { content: b.content ?? "", version: nextVersion(), gitStatus: "added", aiModified: false, aiRanges: [] });
    return { path: b.path, name: b.path.split("/").pop(), type: b.type };
  },
  "projects.files.move": (r) => {
    const b = r.body as MoveFileRequest;
    const files = projectFiles(r.params.projectId!);
    if (b.to === b.from || b.to.startsWith(`${b.from}/`)) fail(409, "file.invalid_move", "A folder can't be moved into itself.");
    if ([...files.keys()].some((p) => p === b.to || p.startsWith(`${b.to}/`))) fail(409, "file.exists", `${b.to} already exists.`);
    let moved = 0;
    for (const [p, f] of [...files]) {
      if (p === b.from || p.startsWith(`${b.from}/`)) {
        files.delete(p);
        files.set(b.to + p.slice(b.from.length), { ...f, gitStatus: "added" });
        moved++;
      }
    }
    if (!moved) notFound("File");
  },
  "projects.files.delete": (r) => {
    const path = String(r.query.path);
    const files = projectFiles(r.params.projectId!);
    for (const p of [...files.keys()]) if (p === path || p.startsWith(`${path}/`)) files.delete(p);
  },
  "projects.files.search": (r) => {
    const q = String(r.query.q ?? "").toLowerCase();
    if (!q) return [];
    const out: { path: string; line: number; column: number; preview: string }[] = [];
    for (const [path, f] of projectFiles(r.params.projectId!)) {
      f.content.split("\n").forEach((text, i) => {
        const col = text.toLowerCase().indexOf(q);
        if (col !== -1 && out.length < 200) out.push({ path, line: i + 1, column: col + 1, preview: text.trim().slice(0, 160) });
      });
    }
    return out;
  },
  "projects.git.log": (r) => (r.params.projectId === "p_trailhead" ? db.gitLog : db.gitLog.slice(-1)),
  "projects.diagnostics": (r) => (r.params.projectId === "p_trailhead" ? db.diagnostics : []),
  "projects.terminal.create": () =>
    fail(501, "not_implemented", "Terminal sessions need the isolated sandbox service, which isn't available in mock mode."),

  // agent
  "agent.tasks.list": (r) => {
    let list = db.tasks;
    if (r.query.projectId) list = list.filter((t) => t.projectId === r.query.projectId);
    if (r.query.status === "active") list = list.filter((t) => !["completed", "failed", "blocked", "cancelled"].includes(t.status));
    return list;
  },
  "agent.tasks.get": (r) => db.tasks.find((t) => t.id === r.params.taskId) ?? notFound("Task"),
  "agent.tasks.timeline": (r) => db.timelines[r.params.taskId!] ?? [],
  "agent.tasks.cancel": (r) => {
    const t = db.tasks.find((x) => x.id === r.params.taskId) ?? notFound("Task");
    t.status = "cancelled";
    t.finishedAt = now();
    t.currentStep = null;
    mockBus.emit(taskEvents(t.id), "task.updated", { type: "task.updated", task: { ...t } });
    return t;
  },
  "agent.messages.list": (r) => db.messages[r.params.projectId!] ?? [],
  "agent.messages.send": (r) => {
    const projectId = r.params.projectId!;
    const b = r.body as SendAgentMessageRequest;
    const list = (db.messages[projectId] ??= []);
    list.push({ id: newId("m"), role: "user", content: b.prompt, intent: b.intent, createdAt: now() });
    const changes = ["generate", "modify", "fix", "refactor"].includes(b.intent);
    if (!changes) {
      const reply: ChatMessage = {
        id: newId("m"),
        role: "assistant",
        createdAt: now(),
        content:
          `(Mock response — no model was called.) In live mode the agent would ${b.intent === "explain" ? "explain" : "answer about"} ` +
          (b.context.activeFile ? `\`${b.context.activeFile}\`` : "your project") +
          (b.context.selection ? ` (lines ${b.context.selection.startLine}–${b.context.selection.endLine})` : "") +
          ".",
      };
      list.push(reply);
      return { message: reply, task: null };
    }
    const task: AgentTask = {
      id: newId("t"), projectId, title: b.prompt.slice(0, 60), description: b.prompt, intent: b.intent, status: "queued",
      currentStep: "Waiting for an agent worker", filesAnalyzing: [], filesModifying: [], buildProgress: null, repairIterations: 0,
      maxRepairIterations: 5, tokenUsage: { inputTokens: 0, outputTokens: 0 }, recordedCostUsd: 0, blockedReason: null,
      errorMessage: null, createdAt: now(), startedAt: now(), finishedAt: null,
    };
    db.tasks.unshift(task);
    db.timelines[task.id] = [{ id: newId("ev"), taskId: task.id, at: now(), status: "queued", title: "Task queued" }];
    const reply: ChatMessage = {
      id: newId("m"), role: "assistant", createdAt: now(), taskId: task.id,
      content: "(Mock response) Working on it — follow progress below.",
      plan: {
        summary: "Mock plan for UI development.",
        steps: [
          { id: "s1", title: "Read the active file and related code", detail: "Collect context from open tabs.", files: b.context.openFiles?.slice(0, 3) ?? [] },
          { id: "s2", title: "Propose edits", detail: "Prepare a change set for review.", files: [] },
          { id: "s3", title: "Build and verify", detail: "Run a debug build before handing back.", files: [] },
        ],
      },
    };
    list.push(reply);
    simulateAgentTask(task, reply);
    return { message: reply, task };
  },
  "agent.changeSets.get": (r) => db.changeSets.find((c) => c.id === r.params.changeSetId) ?? notFound("Change set"),
  "agent.changeSets.decide": (r) => {
    const cs = db.changeSets.find((c) => c.id === r.params.changeSetId) ?? notFound("Change set");
    const { acceptPaths } = r.body as ChangeSetDecisionRequest;
    const task = db.tasks.find((t) => t.id === cs.taskId);
    const files = db.files.get(task?.projectId ?? "");
    const touched: string[] = [];
    for (const fc of cs.files) {
      if (fc.decision !== "pending") continue;
      fc.decision = acceptPaths.includes(fc.path) ? "accepted" : "rejected";
      if (fc.decision !== "accepted" || !files) continue;
      touched.push(fc.path);
      if (fc.changeType === "delete") files.delete(fc.path);
      else {
        const prev = files.get(fc.path);
        const content = fc.proposedContent ?? "";
        files.set(fc.path, {
          content,
          version: nextVersion(),
          gitStatus: fc.changeType === "add" ? "added" : "modified",
          aiModified: true,
          aiRanges: [{ ...(prev ? changedLineRange(prev.content, content) : { startLine: 1, endLine: content.split("\n").length }), taskId: cs.taskId }],
        });
      }
    }
    const accepted = cs.files.filter((f) => f.decision === "accepted").length;
    cs.status = accepted === 0 ? "rejected" : accepted === cs.files.length ? "applied" : "partially_applied";
    if (task && touched.length) mockBus.emit(projectEvents(task.projectId), "files.changed", { type: "files.changed", paths: touched, byAgent: true });
    return cs;
  },

  // builds
  "builds.list": (r) => {
    const list = r.query.projectId ? db.builds.filter((b) => b.projectId === r.query.projectId) : db.builds;
    list.forEach(simulateBuild);
    return [...list].sort((a, b) => b.queuedAt.localeCompare(a.queuedAt));
  },
  "builds.get": (r) => {
    const b = db.builds.find((x) => x.id === r.params.buildId) ?? notFound("Build");
    simulateBuild(b);
    return b;
  },
  "builds.start": (r) => {
    const body = r.body as StartBuildRequest;
    const number = Math.max(0, ...db.builds.filter((b) => b.projectId === body.projectId).map((b) => b.number)) + 1;
    const cap = body.variant === "release" ? "Release" : "Debug";
    const b: Build = {
      id: newId("b"), projectId: body.projectId, number, outputType: body.outputType, variant: body.variant, status: "running",
      gradleTask: body.outputType === "aab" ? `:app:bundle${cap}` : `:app:assemble${cap}`, commitSha: "f04e9a2", triggeredBy: "user",
      agentTaskId: null, queuedAt: now(), startedAt: now(), finishedAt: null, durationMs: null, errorSummary: null, errors: [], artifactIds: [],
    };
    db.builds.unshift(b);
    simulateBuild(b);
    return b;
  },
  "builds.retry": (r) => {
    const prev = db.builds.find((x) => x.id === r.params.buildId) ?? notFound("Build");
    return handlers["builds.start"]!({ ...r, body: { projectId: prev.projectId, outputType: prev.outputType, variant: prev.variant } });
  },
  "builds.cancel": (r) => {
    const b = db.builds.find((x) => x.id === r.params.buildId) ?? notFound("Build");
    b.status = "cancelled";
    b.finishedAt = now();
    return b;
  },
  "builds.logs": (r) => {
    const b = db.builds.find((x) => x.id === r.params.buildId) ?? notFound("Build");
    const existing = db.buildLogs.get(b.id);
    if (existing) return existing.join("\n");
    const lines = [`$ ./gradlew ${b.gradleTask} --console=plain`, "> Configure project :app", "> Task :app:preBuild UP-TO-DATE"];
    if (b.status === "failed") {
      b.errors.forEach((e) => lines.push(`${e.severity === "error" ? "e" : "w"}: ${e.path}:${e.line}:${e.column} ${e.message}`));
      lines.push("", `> Task ${b.errors[0]?.task ?? b.gradleTask} FAILED`, "", "FAILURE: Build failed with an exception.", "", "BUILD FAILED");
    } else if (b.status === "cancelled") lines.push("", "BUILD CANCELLED by user");
    else lines.push(`> Task ${b.gradleTask}`, "", "BUILD SUCCESSFUL");
    db.buildLogs.set(b.id, lines);
    return lines.join("\n");
  },
  "artifacts.list": (r) => db.artifacts.filter((a) => a.buildId === r.query.buildId),
  "artifacts.download": () => fail(501, "not_implemented", "Downloads need artifact storage, which isn't available in mock mode."),

  // tests
  "tests.list": (r) => db.testJobs.filter((j) => j.projectId === r.query.projectId),
  "tests.get": (r) => db.testJobs.find((j) => j.id === r.params.jobId) ?? notFound("Test job"),
  "tests.start": (r) => {
    const b = r.body as StartTestJobRequest;
    const job: TestJob = {
      id: newId("tj"), projectId: b.projectId, buildId: b.buildId ?? null, kind: b.kind, state: "queued", result: null,
      summary: { passed: 0, failed: 0, blocked: 0, unverified: 0, skipped: 0 },
      device: b.kind === "unit" ? null : { name: "Pixel 8", apiLevel: 34, abi: "x86_64" },
      startedAt: null, finishedAt: null, durationMs: null, triggeredBy: "user",
    };
    db.testJobs.unshift(job);
    return job;
  },
  "tests.cases": (r) => db.testCases[r.params.jobId!] ?? [],
  "tests.screenshots": (r) => db.screenshots[r.params.jobId!] ?? [],
  "tests.logs": (r) =>
    (db.testCases[r.params.jobId!] ?? [])
      .map((c) => `[${c.status.toUpperCase().padEnd(10)}] ${c.suite} > ${c.name}${c.failureMessage ? `\n    ${c.failureMessage}` : ""}`)
      .join("\n") || "No output.",

  // usage / billing
  "usage.summary": () => ({
    periodStart: new Date(Date.now() - 18 * 86_400_000).toISOString(),
    periodEnd: db.subscription.currentPeriodEnd,
    aiTokens: { used: 1_284_300, limit: 3_000_000 },
    aiCostUsd: 11.42,
    buildMinutes: { used: 212, limit: 600 },
    storage: { usedBytes: db.projects.reduce((s, p) => s + p.storageBytes, 0), limitBytes: 21_474_836_480 },
    projects: { used: db.projects.length, limit: 20 },
    concurrentAgentTasks: { used: db.tasks.filter((t) => !["completed", "failed", "blocked", "cancelled"].includes(t.status)).length, limit: 3 },
  }),
  "usage.daily": (r) => {
    const days = Number(r.query.days ?? 30);
    const out: UsageDailyPoint[] = [];
    for (let i = days - 1; i >= 0; i--) {
      const d = new Date(Date.now() - i * 86_400_000);
      const seed = Math.abs(Math.sin(d.getDate() * 12.9898) * 43758.5453) % 1;
      const weekend = d.getDay() === 0 || d.getDay() === 6;
      const tokens = Math.round((weekend ? 12_000 : 38_000) + seed * 60_000);
      out.push({ date: d.toISOString().slice(0, 10), aiTokens: tokens, buildMinutes: Math.round(seed * 18 + (weekend ? 1 : 5)), aiCostUsd: +(tokens / 110_000).toFixed(2) });
    }
    return out;
  },
  "billing.plans": () => db.plans,
  "billing.subscription": () => db.subscription,
  "billing.invoices": () => db.invoices,
  "billing.checkout": () => fail(501, "not_implemented", "Checkout needs the billing provider, which isn't connected in mock mode."),
  "billing.portal": () => fail(501, "not_implemented", "The billing portal needs the billing provider, which isn't connected in mock mode."),

  // admin
  "admin.overview": () => ({
    users: 1_284, activeUsers7d: 412, projects: 3_910, buildsToday: 846, buildFailureRate24h: 0.137, agentTasksRunning: 37,
    queueDepth: { builds: 12, agent: 5, tests: 3 }, aiCostTodayUsd: 418.2,
  }),
  "admin.users": () => ({ items: db.adminUsers, nextCursor: null, total: db.adminUsers.length }),
  "admin.workers": () => db.workers,
  "admin.audit": () => db.audit,
};

export const mockTransport: Transport = {
  async request<T>(req: ResolvedRequest): Promise<T> {
    await sleep(120 + Math.random() * 220);
    const handler = handlers[req.key];
    if (!handler) {
      throw new ApiError({
        status: 501,
        code: "not_implemented",
        message: "No backend endpoint for this yet.",
        endpoint: req.key,
      });
    }
    try {
      const result = handler(req);
      // Return copies so React Query never holds references the mock mutates.
      return (result === undefined ? undefined : structuredClone(result)) as T;
    } catch (e) {
      if (e instanceof ApiError) {
        throw new ApiError({ status: e.status, code: e.code, message: e.message, fields: e.fields, endpoint: req.key });
      }
      throw e;
    }
  },
};
