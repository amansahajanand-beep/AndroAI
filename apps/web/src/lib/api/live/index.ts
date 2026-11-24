/**
 * Live transport: maps every contract endpoint key onto the FastAPI backend (docs/API.md).
 * Keys without a handler (agent, billing, usage, preview, terminal, UI editor...) answer
 * 501 `not_implemented`, which screens render as their "waiting for backend" state.
 */
import type {
  AdminOverview,
  ArtifactDownload,
  CreateFileRequest,
  CreateProjectFromPromptRequest,
  CreateProjectResponse,
  EndpointKey,
  FileContent,
  FileNode,
  FileSearchResult,
  LoginRequest,
  MoveFileRequest,
  RegisterRequest,
  ResetPasswordRequest,
  SaveFileRequest,
  Session,
  StartBuildRequest,
  StartTestJobRequest,
  UpdateProfileRequest,
  UpdateProjectRequest,
  UserPreferences,
} from "@apppilot/contracts";
import { ApiError } from "../errors";
import type { ResolvedRequest, Transport } from "../transport";
import { backend, notImplemented } from "./http";
import {
  buildTree, mapActivity, mapAdminUser, mapArtifact, mapAudit, mapBuild, mapOverview, mapPrefs, mapProject, mapTest,
  mapUser, mapWorker, page, prefsToBackend,
  type BActivity, type BArtifact, type BAudit, type BBuild, type BFile, type BOverview, type BPage, type BProject,
  type BTest, type BUser, type BWorker,
} from "./mappers";
import { createUploadSession, getUploadSession } from "./uploads";

type Handler = (r: ResolvedRequest) => Promise<unknown>;

const API = "/api/v1";
const pid = (r: ResolvedRequest) => encodeURIComponent(r.params.projectId ?? "");
const get = <T,>(r: ResolvedRequest, path: string, query?: ResolvedRequest["query"]) =>
  backend<T>("GET", path, { key: r.key, query, signal: r.signal });
const send = <T,>(r: ResolvedRequest, method: string, path: string, body?: unknown, query?: ResolvedRequest["query"]) =>
  backend<T>(method, path, { key: r.key, body, query, signal: r.signal });

async function sessionFrom(r: ResolvedRequest): Promise<Session> {
  const s = await get<{ user: BUser; expires_at: string }>(r, `${API}/auth/session`);
  return { user: mapUser(s.user), expiresAt: s.expires_at };
}

const fileContent = (path: string, content: string, version: string): FileContent => ({ path, content, version, aiRanges: [] });

async function buildsFor(r: ResolvedRequest, projectId?: string) {
  const p = await get<BPage<BBuild>>(r, `${API}/builds`, { project_id: projectId, limit: 100 });
  return p.items.map(mapBuild);
}

const handlers: Partial<Record<EndpointKey, Handler>> = {
  /* ---- auth ---- */
  "auth.session": (r) => sessionFrom(r),
  "auth.login": async (r) => {
    const b = r.body as LoginRequest;
    const out = await send<{ user: BUser; tokens: { access_expires_at: string } }>(r, "POST", `${API}/auth/login`, {
      email: b.email,
      password: b.password,
      remember: b.remember ?? true,
    });
    return { user: mapUser(out.user), expiresAt: out.tokens.access_expires_at } satisfies Session;
  },
  "auth.register": async (r) => {
    const b = r.body as RegisterRequest;
    if (!b.acceptTerms) throw new ApiError({ status: 422, code: "validation_error", message: "Accept the terms to continue.", fields: { acceptTerms: "Required" } });
    await send(r, "POST", `${API}/auth/register`, { email: b.email, password: b.password, display_name: b.name });
    // Registration doesn't sign in on the backend; do it now (cookies are set by this call).
    const out = await backend<{ user: BUser; tokens: { access_expires_at: string } }>("POST", `${API}/auth/login`, {
      key: r.key,
      body: { email: b.email, password: b.password, remember: true },
    });
    return { user: mapUser(out.user), expiresAt: out.tokens.access_expires_at } satisfies Session;
  },
  "auth.logout": async (r) => {
    await send(r, "POST", `${API}/auth/logout`);
  },
  "auth.forgotPassword": async (r) => {
    await send(r, "POST", `${API}/auth/forgot-password`, { email: (r.body as { email: string }).email });
    return { accepted: true };
  },
  "auth.resetPassword": async (r) => {
    const b = r.body as ResetPasswordRequest;
    await send(r, "POST", `${API}/auth/reset-password`, { token: b.token, new_password: b.password });
  },

  /* ---- users ---- */
  "users.me": async (r) => mapUser(await get<BUser>(r, `${API}/users/me`)),
  "users.updateMe": async (r) => {
    const b = r.body as UpdateProfileRequest;
    return mapUser(await send<BUser>(r, "PATCH", `${API}/users/me`, b.name !== undefined ? { display_name: b.name } : {}));
  },
  "users.changePassword": async (r) => {
    const b = r.body as { currentPassword: string; newPassword: string };
    await send(r, "POST", `${API}/auth/change-password`, { current_password: b.currentPassword, new_password: b.newPassword });
  },
  "users.preferences": async (r) => mapPrefs(await get(r, `${API}/users/me/preferences`)),
  "users.updatePreferences": async (r) =>
    mapPrefs(await send(r, "PUT", `${API}/users/me/preferences`, prefsToBackend(r.body as UserPreferences))),

  /* ---- projects ---- */
  "projects.list": async (r) => page(await get<BPage<BProject>>(r, `${API}/projects`, { limit: 100 }), mapProject),
  "projects.get": async (r) => mapProject(await get<BProject>(r, `${API}/projects/${pid(r)}`)),
  "projects.createFromPrompt": async (r): Promise<CreateProjectResponse> => {
    const b = r.body as CreateProjectFromPromptRequest;
    const project = await send<BProject>(r, "POST", `${API}/projects`, {
      name: b.name,
      description: b.description,
      metadata: {
        language: b.language,
        ui_toolkit: b.uiToolkit,
        package_name: b.packageName || undefined,
        min_sdk: b.minSdk,
        target_sdk: b.targetSdk,
        requirements: b.requirements,
        config: b.config,
      },
    });
    // The AI agent API isn't connected yet: the project is created empty and no task is started.
    return { project: mapProject(project), taskId: null };
  },
  "projects.update": async (r) => {
    const b = r.body as UpdateProjectRequest;
    const meta = { package_name: b.packageName, min_sdk: b.minSdk, target_sdk: b.targetSdk };
    return mapProject(
      await send<BProject>(r, "PATCH", `${API}/projects/${pid(r)}`, { name: b.name, description: b.description, metadata: meta }),
    );
  },
  "projects.delete": async (r) => {
    await send(r, "DELETE", `${API}/projects/${pid(r)}`);
  },
  "projects.activity": async (r) => {
    const limit = Number(r.query.limit ?? 15);
    const rows = await get<BActivity[]>(r, `${API}/projects/activity/recent`, { limit: Math.min(100, limit * 4) });
    return rows.map(mapActivity).filter((e) => e !== null).slice(0, limit);
  },
  "projects.uploads.create": async (r) => createUploadSession(r.body as { kind: "android_zip" | "apk"; fileName: string }),
  "projects.uploads.complete": async (r) => getUploadSession(r.params.uploadId ?? ""),
  "projects.uploads.get": async (r) => getUploadSession(r.params.uploadId ?? ""),
  "projects.diagnostics": async (r) => {
    // Problems from the project's most recent finished build.
    const builds = await buildsFor(r, r.params.projectId);
    const last = builds.find((b) => b.status === "failed" || b.status === "succeeded");
    return (last?.errors ?? []).map((e) => ({ path: e.path, line: e.line, column: e.column, severity: e.severity, message: e.message, source: "gradle" }));
  },

  /* ---- files ---- */
  "projects.files.tree": async (r): Promise<FileNode[]> => buildTree(await get<BFile[]>(r, `${API}/projects/${pid(r)}/files`)),
  "projects.files.read": async (r): Promise<FileContent> => {
    const path = String(r.query.path);
    try {
      const f = await get<{ content: string; sha256: string }>(r, `${API}/projects/${pid(r)}/files/content`, { path });
      return fileContent(path, f.content, f.sha256);
    } catch (e) {
      if (e instanceof ApiError && e.code === "binary_file") return { ...fileContent(path, "", "binary"), binary: true };
      throw e;
    }
  },
  "projects.files.save": async (r): Promise<FileContent> => {
    const path = String(r.query.path);
    const b = r.body as SaveFileRequest;
    const out = await send<{ sha256: string }>(r, "PUT", `${API}/projects/${pid(r)}/files/content`, { content: b.content, base_sha256: b.baseVersion }, { path });
    return fileContent(path, b.content, out.sha256);
  },
  "projects.files.create": async (r): Promise<FileNode> => {
    const b = r.body as CreateFileRequest;
    const target = b.type === "dir" ? `${b.path}/.keep` : b.path;
    try {
      await send(r, "PUT", `${API}/projects/${pid(r)}/files/content`, { content: b.content ?? "" }, { path: target });
    } catch (e) {
      if (e instanceof ApiError && e.code === "file.version_conflict") {
        throw new ApiError({ status: 409, code: "file.exists", message: `${b.path} already exists.`, endpoint: r.key });
      }
      throw e;
    }
    return { path: b.path, name: b.path.split("/").pop() ?? b.path, type: b.type };
  },
  "projects.files.move": async (r) => {
    const b = r.body as MoveFileRequest;
    try {
      await send(r, "POST", `${API}/projects/${pid(r)}/files/move`, { from: b.from, to: b.to });
    } catch (e) {
      if (e instanceof ApiError && e.code === "exists") {
        throw new ApiError({ status: 409, code: "file.exists", message: `${b.to} already exists.`, endpoint: r.key });
      }
      throw e;
    }
  },
  "projects.files.delete": async (r) => {
    await send(r, "DELETE", `${API}/projects/${pid(r)}/files`, undefined, { path: String(r.query.path), recursive: true });
  },
  "projects.files.search": async (r): Promise<FileSearchResult[]> => {
    const q = String(r.query.q ?? "").trim();
    return q ? get<FileSearchResult[]>(r, `${API}/projects/${pid(r)}/files/search`, { q }) : [];
  },

  /* ---- builds / artifacts ---- */
  "builds.list": async (r) => buildsFor(r, r.query.projectId ? String(r.query.projectId) : undefined),
  "builds.get": async (r) => mapBuild(await get<BBuild>(r, `${API}/builds/${encodeURIComponent(r.params.buildId ?? "")}`)),
  "builds.start": async (r) => {
    const b = r.body as StartBuildRequest;
    return mapBuild(await send<BBuild>(r, "POST", `${API}/builds`, { project_id: b.projectId, variant: b.variant, output_type: b.outputType }));
  },
  "builds.retry": async (r) => {
    const prev = await get<BBuild>(r, `${API}/builds/${encodeURIComponent(r.params.buildId ?? "")}`);
    return mapBuild(await send<BBuild>(r, "POST", `${API}/builds`, { project_id: prev.project_id, variant: prev.variant, output_type: prev.output_type }));
  },
  "builds.cancel": async (r) => mapBuild(await send<BBuild>(r, "POST", `${API}/builds/${encodeURIComponent(r.params.buildId ?? "")}/cancel`)),
  "builds.logs": async (r) => {
    const id = encodeURIComponent(r.params.buildId ?? "");
    const parts: string[] = [];
    let after = -1;
    for (let i = 0; i < 50; i++) {
      const chunk = await get<{ seq: number; content: string }[]>(r, `${API}/builds/${id}/logs`, { after_seq: after, limit: 1000 });
      parts.push(...chunk.map((c) => c.content));
      if (chunk.length < 1000) break;
      after = chunk[chunk.length - 1]!.seq;
    }
    // Trailing newlines trimmed so line numbers match the SSE stream's `seq`.
    return parts.join("").replace(/\n+$/, "");
  },
  "artifacts.list": async (r) => (await get<BArtifact[]>(r, `${API}/artifacts`, { build_id: String(r.query.buildId ?? "") })).map(mapArtifact),
  "artifacts.download": async (r): Promise<ArtifactDownload> => {
    const d = await send<{ url: string; expires_in: number }>(r, "POST", `${API}/artifacts/${encodeURIComponent(r.params.artifactId ?? "")}/download-url`);
    return { url: d.url, expiresAt: new Date(Date.now() + d.expires_in * 1000).toISOString() };
  },

  /* ---- tests ---- */
  "tests.list": async (r) =>
    (await get<BPage<BTest>>(r, `${API}/tests`, { project_id: String(r.query.projectId ?? ""), limit: 100 })).items.map(mapTest),
  "tests.get": async (r) => mapTest(await get<BTest>(r, `${API}/tests/${encodeURIComponent(r.params.jobId ?? "")}`)),
  "tests.start": async (r) => {
    const b = r.body as StartTestJobRequest;
    return mapTest(
      await send<BTest>(r, "POST", `${API}/tests`, {
        project_id: b.projectId,
        kind: b.kind === "instrumentation" ? "instrumented" : b.kind,
        build_job_id: b.buildId,
      }),
    );
  },

  /* ---- admin ---- */
  "admin.overview": async (r): Promise<AdminOverview> => mapOverview(await get<BOverview>(r, `${API}/admin/overview`)),
  "admin.users": async (r) => page(await get<BPage<BUser>>(r, `${API}/admin/users`, { limit: 100 }), mapAdminUser),
  "admin.workers": async (r) => (await get<BWorker[]>(r, `${API}/admin/workers`)).map(mapWorker),
  "admin.audit": async (r) => (await get<BPage<BAudit>>(r, `${API}/admin/audit-logs`, { limit: 100 })).items.map(mapAudit),
};

export const liveTransport: Transport = {
  async request<T>(req: ResolvedRequest): Promise<T> {
    const handler = handlers[req.key];
    if (!handler) notImplemented(req.key);
    return (await handler!(req)) as T;
  },
};
