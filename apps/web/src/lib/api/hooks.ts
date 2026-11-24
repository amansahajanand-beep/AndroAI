"use client";

/**
 * React Query hooks over the central API client. Screens use these, never
 * `fetch` directly. Query keys live in `qk` so invalidation is consistent.
 */
import { useMutation, useQuery, useQueryClient, type UseQueryOptions } from "@tanstack/react-query";
import type {
  AgentTask,
  ChangeSet,
  ChangeSetDecisionRequest,
  CreateFileRequest,
  CreateProjectFromPromptRequest,
  FileNode,
  LoginRequest,
  MoveFileRequest,
  ProjectEnvVar,
  RegisterRequest,
  SendAgentMessageRequest,
  StartBuildRequest,
  StartTestJobRequest,
  UpdateProfileRequest,
  UpdateProjectRequest,
  UserPreferences,
} from "@apppilot/contracts";
import { TERMINAL_AGENT_STATUSES } from "@apppilot/contracts";
import { api } from "./client";
import { isPendingBackend } from "./errors";

export const qk = {
  session: ["session"] as const,
  me: ["users", "me"] as const,
  prefs: ["users", "prefs"] as const,
  apiKeys: ["users", "apiKeys"] as const,
  projects: ["projects"] as const,
  project: (id: string) => ["projects", id] as const,
  activity: ["projects", "activity"] as const,
  envVars: (id: string) => ["projects", id, "env"] as const,
  upload: (id: string) => ["uploads", id] as const,
  tree: (id: string) => ["projects", id, "tree"] as const,
  file: (id: string, path: string) => ["projects", id, "file", path] as const,
  search: (id: string, q: string) => ["projects", id, "search", q] as const,
  gitLog: (id: string) => ["projects", id, "git"] as const,
  diagnostics: (id: string) => ["projects", id, "diagnostics"] as const,
  tasks: (filter: { projectId?: string; status?: string }) => ["agent", "tasks", filter] as const,
  task: (id: string) => ["agent", "task", id] as const,
  timeline: (id: string) => ["agent", "task", id, "timeline"] as const,
  messages: (projectId: string) => ["agent", "messages", projectId] as const,
  changeSet: (id: string) => ["agent", "changeSet", id] as const,
  builds: (projectId?: string) => ["builds", projectId ?? "all"] as const,
  build: (id: string) => ["build", id] as const,
  buildLogs: (id: string) => ["build", id, "logs"] as const,
  artifacts: (buildId: string) => ["artifacts", buildId] as const,
  tests: (projectId: string) => ["tests", projectId] as const,
  testCases: (jobId: string) => ["tests", "job", jobId, "cases"] as const,
  screenshots: (jobId: string) => ["tests", "job", jobId, "screenshots"] as const,
  testLogs: (jobId: string) => ["tests", "job", jobId, "logs"] as const,
  usage: ["usage"] as const,
  usageDaily: (days: number) => ["usage", "daily", days] as const,
  plans: ["billing", "plans"] as const,
  subscription: ["billing", "subscription"] as const,
  invoices: ["billing", "invoices"] as const,
  admin: (part: string) => ["admin", part] as const,
  uiScreens: (projectId: string) => ["ui", projectId] as const,
  previewSession: (projectId: string) => ["preview", projectId, "session"] as const,
};

type QOpts<T> = Omit<UseQueryOptions<T>, "queryKey" | "queryFn">;

/* ---------------- auth / users ---------------- */

export const useSession = () =>
  useQuery({ queryKey: qk.session, queryFn: api.auth.session, retry: false, staleTime: 5 * 60_000 });

export function useLogin() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (b: LoginRequest) => api.auth.login(b),
    onSuccess: (s) => qc.setQueryData(qk.session, s),
  });
}

export function useRegister() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (b: RegisterRequest) => api.auth.register(b),
    onSuccess: (s) => qc.setQueryData(qk.session, s),
  });
}

export function useLogout() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: api.auth.logout,
    onSettled: () => qc.clear(),
  });
}

export const useForgotPassword = () => useMutation({ mutationFn: api.auth.forgotPassword });
export const useResetPassword = () => useMutation({ mutationFn: api.auth.resetPassword });

export function useUpdateProfile() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (b: UpdateProfileRequest) => api.users.updateMe(b),
    onSuccess: () => qc.invalidateQueries({ queryKey: qk.session }),
  });
}
export const useChangePassword = () => useMutation({ mutationFn: api.users.changePassword });
export const usePreferences = () => useQuery({ queryKey: qk.prefs, queryFn: api.users.preferences });
export function useUpdatePreferences() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (b: UserPreferences) => api.users.updatePreferences(b),
    onSuccess: (p) => qc.setQueryData(qk.prefs, p),
  });
}
export const useApiKeys = () => useQuery({ queryKey: qk.apiKeys, queryFn: api.users.apiKeys });

/* ---------------- projects ---------------- */

export const useProjects = () => useQuery({ queryKey: qk.projects, queryFn: api.projects.list });
export const useProject = (id: string) =>
  useQuery({ queryKey: qk.project(id), queryFn: () => api.projects.get(id), enabled: !!id });
export const useActivity = () => useQuery({ queryKey: qk.activity, queryFn: () => api.projects.activity() });

export function useCreateProject() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (b: CreateProjectFromPromptRequest) => api.projects.createFromPrompt(b),
    onSuccess: () => qc.invalidateQueries({ queryKey: qk.projects }),
  });
}

export function useUpdateProject(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (b: UpdateProjectRequest) => api.projects.update(id, b),
    onSuccess: (p) => {
      qc.setQueryData(qk.project(id), p);
      qc.invalidateQueries({ queryKey: qk.projects, exact: true });
    },
  });
}

export function useDeleteProject() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.projects.remove(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: qk.projects }),
  });
}

export const useEnvVars = (id: string) => useQuery({ queryKey: qk.envVars(id), queryFn: () => api.projects.envVars(id) });
export function useUpdateEnvVars(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (vars: ProjectEnvVar[]) => api.projects.updateEnvVars(id, vars),
    onSuccess: (v) => qc.setQueryData(qk.envVars(id), v),
  });
}

/** Polls an upload session until it's ready or failed. */
export function useUpload(id: string | null) {
  const qc = useQueryClient();
  return useQuery({
    queryKey: qk.upload(id ?? ""),
    queryFn: async () => {
      const s = await api.projects.getUpload(id!);
      // A finished ZIP/APK import has created a project: refresh lists (e.g. the sidebar).
      if (s.status === "ready") qc.invalidateQueries({ queryKey: qk.projects });
      return s;
    },
    enabled: !!id,
    refetchInterval: (q) => {
      const s = q.state.data?.status;
      return s === "ready" || s === "failed" ? false : 1000;
    },
  });
}

/* ---------------- files / git / diagnostics ---------------- */

export const useFileTree = (projectId: string) =>
  useQuery({ queryKey: qk.tree(projectId), queryFn: () => api.files.tree(projectId) });

export const useFile = (projectId: string, path: string | null) =>
  useQuery({
    queryKey: qk.file(projectId, path ?? ""),
    queryFn: () => api.files.read(projectId, path!),
    enabled: !!path,
    staleTime: Number.POSITIVE_INFINITY,
  });

export const useFileSearch = (projectId: string, q: string) =>
  useQuery({
    queryKey: qk.search(projectId, q),
    queryFn: () => api.files.search(projectId, q),
    enabled: q.trim().length >= 2,
  });

export function useFileMutations(projectId: string) {
  const qc = useQueryClient();
  const refresh = () => qc.invalidateQueries({ queryKey: qk.tree(projectId) });
  return {
    create: useMutation({ mutationFn: (b: CreateFileRequest) => api.files.create(projectId, b), onSuccess: refresh }),
    move: useMutation({ mutationFn: (b: MoveFileRequest) => api.files.move(projectId, b), onSuccess: refresh }),
    remove: useMutation({ mutationFn: (path: string) => api.files.remove(projectId, path), onSuccess: refresh }),
    save: useMutation({
      mutationFn: (v: { path: string; content: string; baseVersion: string }) =>
        api.files.save(projectId, v.path, { content: v.content, baseVersion: v.baseVersion }),
      onSuccess: (file) => {
        qc.setQueryData(qk.file(projectId, file.path), file);
        refresh();
      },
    }),
  };
}

export const useGitLog = (projectId: string) =>
  useQuery({ queryKey: qk.gitLog(projectId), queryFn: () => api.projects.gitLog(projectId) });
export const useDiagnostics = (projectId: string) =>
  useQuery({ queryKey: qk.diagnostics(projectId), queryFn: () => api.projects.diagnostics(projectId) });

/* ---------------- agent ---------------- */

const isActive = (t: AgentTask) => !TERMINAL_AGENT_STATUSES.includes(t.status);

export const useAgentTasks = (filter: { projectId?: string; status?: string } = {}, opts?: QOpts<AgentTask[]>) =>
  useQuery({ queryKey: qk.tasks(filter), queryFn: () => api.agent.tasks(filter), ...opts });

export const useAgentTask = (id: string | null) =>
  useQuery({
    queryKey: qk.task(id ?? ""),
    queryFn: () => api.agent.task(id!),
    enabled: !!id,
    // SSE pushes updates; poll slowly as a fallback while active.
    refetchInterval: (q) => (q.state.data && isActive(q.state.data) ? 15_000 : false),
  });

export const useTimeline = (id: string | null) =>
  useQuery({ queryKey: qk.timeline(id ?? ""), queryFn: () => api.agent.timeline(id!), enabled: !!id });

export function useCancelTask() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.agent.cancel(id),
    onSuccess: (t) => {
      qc.setQueryData(qk.task(t.id), t);
      qc.invalidateQueries({ queryKey: ["agent", "tasks"] });
    },
  });
}

export const useMessages = (projectId: string) =>
  useQuery({ queryKey: qk.messages(projectId), queryFn: () => api.agent.messages(projectId) });

export function useSendMessage(projectId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (b: SendAgentMessageRequest) => api.agent.send(projectId, b),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: qk.messages(projectId) });
      qc.invalidateQueries({ queryKey: ["agent", "tasks"] });
    },
  });
}

export const useChangeSet = (id: string | null | undefined) =>
  useQuery({ queryKey: qk.changeSet(id ?? ""), queryFn: () => api.agent.changeSet(id!), enabled: !!id });

export function useDecideChangeSet(projectId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { id: string } & ChangeSetDecisionRequest) => api.agent.decide(v.id, { acceptPaths: v.acceptPaths }),
    onSuccess: (cs: ChangeSet) => {
      qc.setQueryData(qk.changeSet(cs.id), cs);
      qc.invalidateQueries({ queryKey: qk.tree(projectId) });
      cs.files.forEach((f) => qc.invalidateQueries({ queryKey: qk.file(projectId, f.path) }));
    },
  });
}

/* ---------------- builds / artifacts ---------------- */

export const useBuilds = (projectId?: string) =>
  useQuery({
    queryKey: qk.builds(projectId),
    queryFn: () => api.builds.list(projectId),
    refetchInterval: (q) => (q.state.data?.some((b) => b.status === "running" || b.status === "queued") ? 5000 : false),
  });

export const useBuild = (id: string | null) =>
  useQuery({ queryKey: qk.build(id ?? ""), queryFn: () => api.builds.get(id!), enabled: !!id });

export const useBuildLogs = (id: string | null) =>
  useQuery({ queryKey: qk.buildLogs(id ?? ""), queryFn: () => api.builds.logs(id!), enabled: !!id });

export function useBuildActions(projectId: string) {
  const qc = useQueryClient();
  const refresh = () => qc.invalidateQueries({ queryKey: ["builds"] });
  return {
    start: useMutation({ mutationFn: (b: StartBuildRequest) => api.builds.start(b), onSuccess: refresh }),
    retry: useMutation({ mutationFn: (id: string) => api.builds.retry(id), onSuccess: refresh }),
    cancel: useMutation({ mutationFn: (id: string) => api.builds.cancel(id), onSuccess: refresh }),
    projectId,
  };
}

export const useArtifacts = (buildId: string | null) =>
  useQuery({ queryKey: qk.artifacts(buildId ?? ""), queryFn: () => api.artifacts.list(buildId!), enabled: !!buildId });

/* ---------------- tests ---------------- */

export const useTestJobs = (projectId: string) =>
  useQuery({ queryKey: qk.tests(projectId), queryFn: () => api.tests.list(projectId) });
export const useTestCases = (jobId: string | null) =>
  useQuery({ queryKey: qk.testCases(jobId ?? ""), queryFn: () => api.tests.cases(jobId!), enabled: !!jobId });
export const useScreenshots = (jobId: string | null) =>
  useQuery({ queryKey: qk.screenshots(jobId ?? ""), queryFn: () => api.tests.screenshots(jobId!), enabled: !!jobId });
export const useTestLogs = (jobId: string | null) =>
  useQuery({ queryKey: qk.testLogs(jobId ?? ""), queryFn: () => api.tests.logs(jobId!), enabled: !!jobId });
export function useStartTests(projectId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (b: StartTestJobRequest) => api.tests.start(b),
    onSuccess: () => qc.invalidateQueries({ queryKey: qk.tests(projectId) }),
  });
}

/* ---------------- usage / billing / admin ---------------- */

export const useUsage = () => useQuery({ queryKey: qk.usage, queryFn: api.usage.summary });
export const useUsageDaily = (days = 30) =>
  useQuery({ queryKey: qk.usageDaily(days), queryFn: () => api.usage.daily(days) });
export const usePlans = () => useQuery({ queryKey: qk.plans, queryFn: api.billing.plans, staleTime: 60 * 60_000 });
export const useSubscription = () => useQuery({ queryKey: qk.subscription, queryFn: api.billing.subscription });
export const useInvoices = () => useQuery({ queryKey: qk.invoices, queryFn: api.billing.invoices });

export const useAdminOverview = () => useQuery({ queryKey: qk.admin("overview"), queryFn: api.admin.overview, refetchInterval: 30_000 });
export const useAdminUsers = () => useQuery({ queryKey: qk.admin("users"), queryFn: api.admin.users });
export const useAdminWorkers = () => useQuery({ queryKey: qk.admin("workers"), queryFn: api.admin.workers, refetchInterval: 15_000 });
export const useAdminAudit = () => useQuery({ queryKey: qk.admin("audit"), queryFn: api.admin.audit });

export const useUiScreens = (projectId: string, opts?: { enabled?: boolean }) =>
  useQuery({ queryKey: qk.uiScreens(projectId), queryFn: () => api.ui.screens(projectId), enabled: opts?.enabled ?? true });

/**
 * Starts an emulator stream session while the Preview view is open. Each open
 * creates a fresh session (gcTime 0), so it is only enabled while visible.
 */
export const useEmulatorSession = (projectId: string, enabled: boolean) =>
  useQuery({
    queryKey: qk.previewSession(projectId),
    queryFn: ({ signal }) => api.preview.start(projectId, {}, signal),
    enabled,
    retry: false,
    staleTime: Infinity,
    gcTime: 0,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
  });

/* ---------------- shared ---------------- */

/** Don't retry calls that failed because the endpoint doesn't exist yet. */
export function shouldRetry(failureCount: number, error: unknown) {
  if (isPendingBackend(error)) return false;
  if (error && typeof error === "object" && "status" in error) {
    const s = (error as { status: number }).status;
    if (s >= 400 && s < 500) return false;
  }
  return failureCount < 2;
}

export type { FileNode };
