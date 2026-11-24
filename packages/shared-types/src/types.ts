/**
 * Frontend <-> backend API types.
 *
 * Reconstructed from how apps/web uses them (the original package was not in the repo).
 * The live transport (apps/web/src/lib/api/live) maps the FastAPI responses documented in
 * docs/API.md onto these shapes; endpoints with no backend yet are marked `planned` in
 * ENDPOINTS and answer 501 so screens show their "waiting for backend" state.
 */

/* ---------------- common ---------------- */

export interface ApiErrorBody {
  error: { code: string; message: string; fields?: Record<string, string>; requestId?: string; details?: unknown };
}

export interface Paginated<T> {
  items: T[];
  nextCursor: string | null;
  total: number;
}

/* ---------------- auth / users ---------------- */

export type UserRole = "user" | "admin";

export interface User {
  id: string;
  name: string;
  email: string;
  avatarUrl: string | null;
  role: UserRole;
  emailVerified: boolean;
  createdAt: string;
}

export interface Session {
  user: User;
  expiresAt: string;
}

export interface LoginRequest {
  email: string;
  password: string;
  remember?: boolean;
}
export interface RegisterRequest {
  name: string;
  email: string;
  password: string;
  acceptTerms: boolean;
}
export interface ForgotPasswordRequest {
  email: string;
}
export interface ForgotPasswordResponse {
  accepted: boolean;
}
export interface ResetPasswordRequest {
  token: string;
  password: string;
}
export interface ChangePasswordRequest {
  currentPassword: string;
  newPassword: string;
}
export interface UpdateProfileRequest {
  name?: string;
  avatarUrl?: string | null;
}

export type ProjectLanguage = "kotlin" | "java";
export type UiToolkit = "compose" | "xml";

export interface UserPreferences {
  theme: "light" | "dark" | "system";
  defaultLanguage: ProjectLanguage;
  defaultUiToolkit: UiToolkit;
  emailNotifications: { buildFailed: boolean; agentTaskCompleted: boolean; usageThreshold: boolean };
}

export interface ApiKeySummary {
  id: string;
  name: string;
  lastFour: string;
  createdAt: string;
  lastUsedAt: string | null;
}

/* ---------------- projects ---------------- */

export type ProjectSource = "prompt" | "android_zip" | "apk";
export type ProjectStatus = "creating" | "analyzing" | "ready" | "error";

export interface Project {
  id: string;
  name: string;
  description: string;
  source: ProjectSource;
  status: ProjectStatus;
  language: ProjectLanguage;
  uiToolkit: UiToolkit;
  packageName: string | null;
  minSdk: number;
  targetSdk: number;
  isApkAnalysis: boolean;
  activeTaskCount: number;
  lastBuild: { id: string; status: BuildStatus; finishedAt: string | null } | null;
  storageBytes: number;
  createdAt: string;
  updatedAt: string;
}

export interface CreateProjectFromPromptRequest {
  name: string;
  description: string;
  language: ProjectLanguage;
  uiToolkit: UiToolkit;
  requirements: string[];
  packageName?: string;
  minSdk?: number;
  targetSdk?: number;
  config: Record<string, string>;
}
/** `taskId` is null until the AI agent API is connected: the project is created empty. */
export interface CreateProjectResponse {
  project: Project;
  taskId: string | null;
}
export interface UpdateProjectRequest {
  name?: string;
  description?: string;
  packageName?: string;
  minSdk?: number;
  targetSdk?: number;
}
export interface ProjectEnvVar {
  key: string;
  value: string | null;
  secret: boolean;
}

export type ActivityKind =
  | "project_created"
  | "agent_task_started"
  | "agent_task_completed"
  | "agent_task_failed"
  | "build_succeeded"
  | "build_failed"
  | "tests_passed"
  | "tests_failed"
  | "files_changed";
export interface ActivityEvent {
  id: string;
  projectId: string;
  projectName: string;
  kind: ActivityKind;
  message: string;
  at: string;
}

/* ---------------- uploads ---------------- */

export type UploadKind = "android_zip" | "apk";
export type UploadStatus = "uploading" | "validating" | "analyzing" | "ready" | "failed";
/** Outcome of a test case / test job. `blocked` and `unverified` are NOT passes. */
export type ValidationStatus = "passed" | "failed" | "blocked" | "unverified" | "skipped";

export interface CreateUploadRequest {
  kind: UploadKind;
  fileName: string;
  sizeBytes?: number;
}

export interface ZipAnalysis {
  gradleWrapper: boolean;
  buildSystem: "gradle-kts" | "gradle-groovy" | "unknown";
  modules: string[];
  language: ProjectLanguage;
  uiToolkit: UiToolkit;
  agpVersion: string | null;
  kotlinVersion: string | null;
  fileCount: number;
  warnings: string[];
}

export interface ApkFinding {
  severity: "info" | "warning" | "risk";
  message: string;
}
/** APKs are validated and stored but never unpacked on the control plane, so most fields are optional. */
export interface ApkAnalysis {
  packageName: string | null;
  versionName: string | null;
  versionCode: number | null;
  minSdk: number | null;
  targetSdk: number | null;
  sizeBytes: number;
  permissions: string[];
  activities: string[];
  services: string[];
  receivers: string[];
  nativeAbis: string[];
  detectedLibraries: string[];
  obfuscated: boolean | null;
  findings: ApkFinding[];
}

export interface UploadSession {
  id: string;
  kind: UploadKind;
  status: UploadStatus;
  /** Same-origin API URL (live) or a placeholder (mock). */
  uploadUrl: string;
  analysisProgress: number;
  validationErrors: string[];
  projectId: string | null;
  zipAnalysis: ZipAnalysis | null;
  apkAnalysis: ApkAnalysis | null;
}

/* ---------------- files / editor ---------------- */

export type GitFileStatus = "added" | "modified" | "deleted" | "untracked";

export interface FileNode {
  path: string;
  name: string;
  type: "file" | "dir";
  children?: FileNode[];
  sizeBytes?: number;
  gitStatus?: GitFileStatus | null;
  aiModified?: boolean;
}
export interface AiRange {
  startLine: number;
  endLine: number;
  taskId: string;
}
export interface FileContent {
  path: string;
  content: string;
  /** Opaque version token; send it back as `baseVersion` when saving. */
  version: string;
  aiRanges: AiRange[];
  binary?: boolean;
}
export interface SaveFileRequest {
  content: string;
  baseVersion: string;
}
export interface CreateFileRequest {
  path: string;
  type: "file" | "dir";
  content?: string;
}
export interface MoveFileRequest {
  from: string;
  to: string;
}
export interface FileSearchResult {
  path: string;
  line: number;
  column: number;
  preview: string;
}
export interface GitCommit {
  sha: string;
  message: string;
  author: string;
  authoredAt: string;
  filesChanged: number;
  aiTaskId: string | null;
}
export interface Diagnostic {
  path: string;
  line: number;
  column: number;
  severity: "error" | "warning" | "info";
  message: string;
  source: string;
}
export interface TerminalSession {
  id: string;
  wsUrl: string;
}
export type TerminalClientFrame =
  | { type: "input"; data: string }
  | { type: "resize"; cols: number; rows: number };
export type TerminalServerFrame = { type: "output"; data: string } | { type: "exit"; code: number };

/* ---------------- agent ---------------- */

export const AGENT_TASK_STATUSES = [
  "queued",
  "planning",
  "analyzing",
  "generating",
  "reviewing",
  "building",
  "repairing",
  "testing",
  "completed",
  "failed",
  "blocked",
  "cancelled",
] as const;
export type AgentTaskStatus = (typeof AGENT_TASK_STATUSES)[number];
export const TERMINAL_AGENT_STATUSES: readonly AgentTaskStatus[] = ["completed", "failed", "blocked", "cancelled"];

export type AgentIntent = "generate" | "modify" | "fix" | "refactor" | "explain" | "chat";

export interface AgentTask {
  id: string;
  projectId: string;
  title: string;
  description: string;
  intent: AgentIntent;
  status: AgentTaskStatus;
  currentStep: string | null;
  filesAnalyzing: string[];
  filesModifying: string[];
  buildProgress: { percent: number; phase: string } | null;
  repairIterations: number;
  maxRepairIterations: number;
  tokenUsage: { inputTokens: number; outputTokens: number };
  recordedCostUsd: number;
  blockedReason: string | null;
  errorMessage: string | null;
  createdAt: string;
  startedAt: string | null;
  finishedAt: string | null;
}
export interface AgentTimelineEvent {
  id: string;
  taskId: string;
  at: string;
  status: AgentTaskStatus;
  title: string;
  detail?: string;
  files?: string[];
}
export interface PlanStep {
  id: string;
  title: string;
  detail: string;
  files: string[];
}
export interface ChatMessage {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  intent?: AgentIntent;
  createdAt: string;
  taskId?: string;
  plan?: { summary: string; steps: PlanStep[] };
  changeSetId?: string;
}
export interface SendAgentMessageRequest {
  prompt: string;
  intent: AgentIntent;
  context: {
    activeFile?: string;
    selection?: { startLine: number; endLine: number };
    openFiles?: string[];
    diagnostics?: { path: string; line: number; message: string }[];
  };
}
export interface SendAgentMessageResponse {
  message: ChatMessage;
  task: AgentTask | null;
}
export interface FileChange {
  path: string;
  changeType: "add" | "modify" | "delete";
  originalContent: string | null;
  proposedContent: string | null;
  decision: "pending" | "accepted" | "rejected";
}
export interface ChangeSet {
  id: string;
  taskId: string;
  summary: string;
  status: "pending" | "applied" | "partially_applied" | "rejected";
  files: FileChange[];
}
export interface ChangeSetDecisionRequest {
  acceptPaths: string[];
}
export type AgentStreamEvent =
  | { type: "task.updated"; task: AgentTask }
  | { type: "timeline.appended"; event: AgentTimelineEvent }
  | { type: "message.completed"; message: ChatMessage }
  | { type: "changeset.ready"; changeSet: ChangeSet };
export type ProjectStreamEvent =
  | { type: "build.updated"; buildId: string; status: BuildStatus }
  | { type: "task.updated"; taskId: string; status: AgentTaskStatus }
  | { type: "files.changed"; paths: string[]; byAgent: boolean }
  | { type: "diagnostics.updated" };

/* ---------------- builds / artifacts ---------------- */

export type BuildStatus = "queued" | "running" | "succeeded" | "failed" | "cancelled";
export type BuildVariant = "debug" | "release";
export type BuildOutputType = "apk" | "aab";

export interface BuildErrorItem {
  path: string;
  line: number;
  column: number;
  severity: "error" | "warning";
  message: string;
  task: string;
}
export interface Build {
  id: string;
  projectId: string;
  number: number;
  outputType: BuildOutputType;
  variant: BuildVariant;
  status: BuildStatus;
  gradleTask: string;
  commitSha: string;
  triggeredBy: "user" | "agent";
  agentTaskId: string | null;
  queuedAt: string;
  startedAt: string | null;
  finishedAt: string | null;
  durationMs: number | null;
  errorSummary: string | null;
  errors: BuildErrorItem[];
  artifactIds: string[];
}
export interface BuildLogLine {
  seq: number;
  line: string;
}
export interface StartBuildRequest {
  projectId: string;
  outputType: BuildOutputType;
  variant: BuildVariant;
}
export interface Artifact {
  id: string;
  projectId: string;
  buildId: string | null;
  kind: "apk" | "aab" | "mapping" | "log" | "report" | "upload";
  fileName: string;
  sizeBytes: number;
  sha256: string;
  createdAt: string;
  expiresAt: string | null;
}
export interface ArtifactDownload {
  url: string;
  expiresAt: string;
}

/* ---------------- tests ---------------- */

export type TestJobKind = "unit" | "emulator" | "instrumentation";
export interface TestSummary {
  passed: number;
  failed: number;
  blocked: number;
  unverified: number;
  skipped: number;
}
export interface TestJob {
  id: string;
  projectId: string;
  buildId: string | null;
  kind: TestJobKind;
  state: "queued" | "running" | "finished";
  /** null until finished. `blocked`/`unverified` mean the runtime could not verify: never "passed". */
  result: "passed" | "failed" | "blocked" | "unverified" | null;
  summary: TestSummary;
  device: { name: string; apiLevel: number; abi: string } | null;
  startedAt: string | null;
  finishedAt: string | null;
  durationMs: number | null;
  triggeredBy: "user" | "agent";
  /** Why a queued/finished job could not run, when the backend knows. */
  reason?: string | null;
}
export interface TestCase {
  id: string;
  jobId: string;
  suite: string;
  name: string;
  status: "passed" | "failed" | "blocked" | "unverified" | "skipped";
  durationMs: number | null;
  failureMessage: string | null;
  stackTrace: string | null;
}
export interface TestScreenshot {
  id: string;
  jobId: string;
  testCaseId: string;
  url: string;
  caption: string;
  takenAt: string;
}
export interface StartTestJobRequest {
  projectId: string;
  kind: TestJobKind;
  buildId?: string;
}

/* ---------------- usage / billing ---------------- */

export interface UsageSummary {
  periodStart: string;
  periodEnd: string;
  aiTokens: { used: number; limit: number | null };
  aiCostUsd: number;
  buildMinutes: { used: number; limit: number | null };
  storage: { usedBytes: number; limitBytes: number | null };
  projects: { used: number; limit: number | null };
  concurrentAgentTasks: { used: number; limit: number | null };
}
export interface UsageDailyPoint {
  date: string;
  aiTokens: number;
  buildMinutes: number;
  aiCostUsd: number;
}
export interface Plan {
  id: string;
  name: string;
  priceMonthlyUsd: number;
  limits: {
    aiTokensPerMonth: number | null;
    buildMinutesPerMonth: number | null;
    storageBytes: number | null;
    projects: number | null;
    concurrentAgentTasks: number | null;
  };
  features: string[];
}
export interface Subscription {
  planId: string;
  status: "active" | "trialing" | "past_due" | "cancelled";
  currentPeriodEnd: string;
  cancelAtPeriodEnd: boolean;
}
export interface Invoice {
  id: string;
  issuedAt: string;
  amountUsd: number;
  status: "paid" | "open" | "failed" | "void";
  pdfUrl: string | null;
}
export interface RedirectUrl {
  url: string;
}

/* ---------------- admin ---------------- */

export interface AdminOverview {
  users: number;
  activeUsers7d: number;
  projects: number;
  buildsToday: number;
  buildFailureRate24h: number;
  agentTasksRunning: number;
  queueDepth: { builds: number; agent: number; tests: number };
  aiCostTodayUsd: number;
}
export interface AdminUser extends User {
  planId: string;
  status: "active" | "suspended";
  projectCount: number;
  lastActiveAt: string | null;
}
export interface WorkerStatus {
  id: string;
  pool: "build" | "agent" | "emulator" | "test";
  state: "idle" | "busy" | "draining" | "offline";
  currentJobId: string | null;
  lastHeartbeatAt: string | null;
}
export interface AdminAuditEvent {
  id: string;
  actorEmail: string;
  action: string;
  target: string;
  at: string;
}

/* ---------------- preview / visual editor ---------------- */

export interface PreviewDevice {
  name: string;
  apiLevel: number;
  width: number;
  height: number;
}
export type PreviewErrorCode =
  | "no_build"
  | "build_failed"
  | "build_in_progress"
  | "emulator_unavailable"
  | "unsupported_project";
export interface StartPreviewSessionRequest {
  device?: Partial<PreviewDevice>;
}
export interface EmulatorStreamSession {
  sessionId: string;
  state: "starting" | "ready";
  viewerUrl: string;
  device: PreviewDevice;
  expiresAt: string;
}
export interface UiNode {
  id: string;
  component: string;
  props: Record<string, string | number | boolean | null>;
  source: { path: string; startLine: number };
  children: UiNode[];
}
export interface UiScreen {
  id: string;
  name: string;
  root: UiNode;
  previewUrl: string | null;
}
export type UiEdit =
  | { kind: "setProp"; nodeId: string; prop: string; value: string }
  | { kind: "prompt"; nodeId: string | null; instruction: string };
export interface ApplyUiEditsRequest {
  edits: UiEdit[];
}
export interface ApplyUiEditsResponse {
  screen: UiScreen;
  changeSet: ChangeSet;
}
