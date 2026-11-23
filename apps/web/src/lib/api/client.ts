/**
 * Centralized API client. Every request goes through `call()` with an
 * endpoint key from @apppilot/contracts, so paths and owners are never
 * hard-coded in screens.
 */
import {
  ENDPOINTS,
  type AdminAuditEvent,
  type AdminOverview,
  type AdminUser,
  type AgentTask,
  type AgentTimelineEvent,
  type ApiKeySummary,
  type Artifact,
  type ArtifactDownload,
  type ActivityEvent,
  type Build,
  type ChangePasswordRequest,
  type ChangeSet,
  type ChangeSetDecisionRequest,
  type ChatMessage,
  type CreateFileRequest,
  type CreateProjectFromPromptRequest,
  type CreateProjectResponse,
  type CreateUploadRequest,
  type Diagnostic,
  type EndpointKey,
  type FileContent,
  type FileNode,
  type FileSearchResult,
  type ForgotPasswordRequest,
  type ForgotPasswordResponse,
  type GitCommit,
  type Invoice,
  type LoginRequest,
  type MoveFileRequest,
  type Paginated,
  type Plan,
  type Project,
  type EmulatorStreamSession,
  type StartPreviewSessionRequest,
  type ProjectEnvVar,
  type RedirectUrl,
  type RegisterRequest,
  type ResetPasswordRequest,
  type SaveFileRequest,
  type SendAgentMessageRequest,
  type SendAgentMessageResponse,
  type Session,
  type StartBuildRequest,
  type StartTestJobRequest,
  type Subscription,
  type TerminalSession,
  type TestCase,
  type TestJob,
  type TestScreenshot,
  type UiScreen,
  type UpdateProfileRequest,
  type UpdateProjectRequest,
  type UploadSession,
  type UsageDailyPoint,
  type UsageSummary,
  type User,
  type UserPreferences,
  type WorkerStatus,
  type ApplyUiEditsRequest,
  type ApplyUiEditsResponse,
} from "@apppilot/contracts";
import { getTransport, resolvePath, type RequestOptions } from "./transport";

export async function call<T>(key: EndpointKey, opts: RequestOptions = {}): Promise<T> {
  const spec = ENDPOINTS[key];
  if (spec.method === "SSE" || spec.method === "WS") {
    throw new Error(`${key} is a stream; use the realtime helpers.`);
  }
  const transport = await getTransport();
  return transport.request<T>({
    key,
    method: spec.method,
    path: resolvePath(key, opts.params),
    params: opts.params ?? {},
    query: opts.query ?? {},
    body: opts.body,
    signal: opts.signal,
  });
}

const p = (projectId: string) => ({ projectId });

export const api = {
  auth: {
    session: () => call<Session>("auth.session"),
    login: (body: LoginRequest) => call<Session>("auth.login", { body }),
    register: (body: RegisterRequest) => call<Session>("auth.register", { body }),
    logout: () => call<void>("auth.logout", { body: {} }),
    forgotPassword: (body: ForgotPasswordRequest) =>
      call<ForgotPasswordResponse>("auth.forgotPassword", { body }),
    resetPassword: (body: ResetPasswordRequest) => call<void>("auth.resetPassword", { body }),
  },
  users: {
    me: () => call<User>("users.me"),
    updateMe: (body: UpdateProfileRequest) => call<User>("users.updateMe", { body }),
    changePassword: (body: ChangePasswordRequest) => call<void>("users.changePassword", { body }),
    preferences: () => call<UserPreferences>("users.preferences"),
    updatePreferences: (body: UserPreferences) =>
      call<UserPreferences>("users.updatePreferences", { body }),
    apiKeys: () => call<ApiKeySummary[]>("users.apiKeys"),
  },
  projects: {
    list: () => call<Paginated<Project>>("projects.list", { query: { limit: 100 } }),
    get: (projectId: string) => call<Project>("projects.get", { params: p(projectId) }),
    createFromPrompt: (body: CreateProjectFromPromptRequest) =>
      call<CreateProjectResponse>("projects.createFromPrompt", { body }),
    update: (projectId: string, body: UpdateProjectRequest) =>
      call<Project>("projects.update", { params: p(projectId), body }),
    remove: (projectId: string) => call<void>("projects.delete", { params: p(projectId) }),
    activity: (limit = 15) => call<ActivityEvent[]>("projects.activity", { query: { limit } }),
    envVars: (projectId: string) => call<ProjectEnvVar[]>("projects.envVars", { params: p(projectId) }),
    updateEnvVars: (projectId: string, body: ProjectEnvVar[]) =>
      call<ProjectEnvVar[]>("projects.updateEnvVars", { params: p(projectId), body }),
    createUpload: (body: CreateUploadRequest) => call<UploadSession>("projects.uploads.create", { body }),
    completeUpload: (uploadId: string) =>
      call<UploadSession>("projects.uploads.complete", { params: { uploadId }, body: {} }),
    getUpload: (uploadId: string) => call<UploadSession>("projects.uploads.get", { params: { uploadId } }),
    createTerminal: (projectId: string) =>
      call<TerminalSession>("projects.terminal.create", { params: p(projectId), body: {} }),
    diagnostics: (projectId: string) => call<Diagnostic[]>("projects.diagnostics", { params: p(projectId) }),
    gitLog: (projectId: string) => call<GitCommit[]>("projects.git.log", { params: p(projectId) }),
  },
  files: {
    tree: (projectId: string) => call<FileNode[]>("projects.files.tree", { params: p(projectId) }),
    read: (projectId: string, path: string) =>
      call<FileContent>("projects.files.read", { params: p(projectId), query: { path } }),
    save: (projectId: string, path: string, body: SaveFileRequest) =>
      call<FileContent>("projects.files.save", { params: p(projectId), query: { path }, body }),
    create: (projectId: string, body: CreateFileRequest) =>
      call<FileNode>("projects.files.create", { params: p(projectId), body }),
    move: (projectId: string, body: MoveFileRequest) =>
      call<void>("projects.files.move", { params: p(projectId), body }),
    remove: (projectId: string, path: string) =>
      call<void>("projects.files.delete", { params: p(projectId), query: { path } }),
    search: (projectId: string, q: string) =>
      call<FileSearchResult[]>("projects.files.search", { params: p(projectId), query: { q } }),
  },
  agent: {
    tasks: (query: { projectId?: string; status?: string } = {}) =>
      call<AgentTask[]>("agent.tasks.list", { query }),
    task: (taskId: string) => call<AgentTask>("agent.tasks.get", { params: { taskId } }),
    timeline: (taskId: string) => call<AgentTimelineEvent[]>("agent.tasks.timeline", { params: { taskId } }),
    cancel: (taskId: string) => call<AgentTask>("agent.tasks.cancel", { params: { taskId }, body: {} }),
    messages: (projectId: string) => call<ChatMessage[]>("agent.messages.list", { params: p(projectId) }),
    send: (projectId: string, body: SendAgentMessageRequest) =>
      call<SendAgentMessageResponse>("agent.messages.send", { params: p(projectId), body }),
    changeSet: (changeSetId: string) => call<ChangeSet>("agent.changeSets.get", { params: { changeSetId } }),
    decide: (changeSetId: string, body: ChangeSetDecisionRequest) =>
      call<ChangeSet>("agent.changeSets.decide", { params: { changeSetId }, body }),
  },
  builds: {
    list: (projectId?: string) => call<Build[]>("builds.list", { query: { projectId } }),
    get: (buildId: string) => call<Build>("builds.get", { params: { buildId } }),
    start: (body: StartBuildRequest) => call<Build>("builds.start", { body }),
    retry: (buildId: string) => call<Build>("builds.retry", { params: { buildId }, body: {} }),
    cancel: (buildId: string) => call<Build>("builds.cancel", { params: { buildId }, body: {} }),
    logs: (buildId: string) => call<string>("builds.logs", { params: { buildId } }),
  },
  artifacts: {
    list: (buildId: string) => call<Artifact[]>("artifacts.list", { query: { buildId } }),
    download: (artifactId: string) =>
      call<ArtifactDownload>("artifacts.download", { params: { artifactId } }),
  },
  tests: {
    list: (projectId: string) => call<TestJob[]>("tests.list", { query: { projectId } }),
    get: (jobId: string) => call<TestJob>("tests.get", { params: { jobId } }),
    start: (body: StartTestJobRequest) => call<TestJob>("tests.start", { body }),
    cases: (jobId: string) => call<TestCase[]>("tests.cases", { params: { jobId } }),
    screenshots: (jobId: string) => call<TestScreenshot[]>("tests.screenshots", { params: { jobId } }),
    logs: (jobId: string) => call<string>("tests.logs", { params: { jobId } }),
  },
  usage: {
    summary: () => call<UsageSummary>("usage.summary"),
    daily: (days = 30) => call<UsageDailyPoint[]>("usage.daily", { query: { days } }),
  },
  billing: {
    plans: () => call<Plan[]>("billing.plans"),
    subscription: () => call<Subscription>("billing.subscription"),
    invoices: () => call<Invoice[]>("billing.invoices"),
    checkout: (planId: string) => call<RedirectUrl>("billing.checkout", { body: { planId } }),
    portal: () => call<RedirectUrl>("billing.portal", { body: {} }),
  },
  admin: {
    overview: () => call<AdminOverview>("admin.overview"),
    users: () => call<Paginated<AdminUser>>("admin.users"),
    workers: () => call<WorkerStatus[]>("admin.workers"),
    audit: () => call<AdminAuditEvent[]>("admin.audit"),
  },
  preview: {
    start: (projectId: string, body: StartPreviewSessionRequest = {}, signal?: AbortSignal) =>
      call<EmulatorStreamSession>("preview.start", { params: p(projectId), body, signal }),
    stop: (projectId: string, sessionId: string) => call<void>("preview.stop", { params: { projectId, sessionId } }),
  },
  ui: {
    screens: (projectId: string) => call<UiScreen[]>("ui.screens", { params: p(projectId) }),
    screen: (projectId: string, screenId: string) =>
      call<UiScreen>("ui.screen", { params: { projectId, screenId } }),
    applyEdits: (projectId: string, screenId: string, body: ApplyUiEditsRequest) =>
      call<ApplyUiEditsResponse>("ui.edits", { params: { projectId, screenId }, body }),
  },
};
