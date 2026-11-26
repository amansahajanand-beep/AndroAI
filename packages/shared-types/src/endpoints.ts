/**
 * Endpoint registry used by apps/web (`call(key)`), keyed by feature.
 *
 * `path` is the REAL FastAPI route for implemented endpoints (docs/API.md); the live
 * transport maps request/response shapes between the frontend types and the backend.
 * `status`: "live" = backed by the API today, "planned" = no backend yet (the transport
 * answers 501 not_implemented and the screen shows its waiting state).
 * `owner` is who delivers the backend side.
 */
export type HttpMethod = "GET" | "POST" | "PUT" | "PATCH" | "DELETE" | "SSE" | "WS";
export type Owner = "backend" | "agent" | "codegen" | "infra";
export type ContractStatus = "live" | "planned";

export interface EndpointSpec {
  method: HttpMethod;
  path: string;
  owner: Owner;
  status: ContractStatus;
}

const e = (method: HttpMethod, path: string, owner: Owner, status: ContractStatus): EndpointSpec => ({
  method,
  path,
  owner,
  status,
});
const B = "backend" as const;
const A = "agent" as const;

export const ENDPOINTS = {
  // auth
  "auth.session": e("GET", "/api/v1/auth/session", B, "live"),
  "auth.login": e("POST", "/api/v1/auth/login", B, "live"),
  "auth.register": e("POST", "/api/v1/auth/register", B, "live"),
  "auth.logout": e("POST", "/api/v1/auth/logout", B, "live"),
  "auth.forgotPassword": e("POST", "/api/v1/auth/forgot-password", B, "live"),
  "auth.resetPassword": e("POST", "/api/v1/auth/reset-password", B, "live"),
  // users
  "users.me": e("GET", "/api/v1/users/me", B, "live"),
  "users.updateMe": e("PATCH", "/api/v1/users/me", B, "live"),
  "users.changePassword": e("POST", "/api/v1/auth/change-password", B, "live"),
  "users.preferences": e("GET", "/api/v1/users/me/preferences", B, "live"),
  "users.updatePreferences": e("PUT", "/api/v1/users/me/preferences", B, "live"),
  "users.apiKeys": e("GET", "/api/v1/users/me/api-keys", B, "planned"),
  // projects
  "projects.list": e("GET", "/api/v1/projects", B, "live"),
  "projects.get": e("GET", "/api/v1/projects/{projectId}", B, "live"),
  "projects.createFromPrompt": e("POST", "/api/v1/projects", B, "live"),
  "projects.update": e("PATCH", "/api/v1/projects/{projectId}", B, "live"),
  "projects.delete": e("DELETE", "/api/v1/projects/{projectId}", B, "live"),
  "projects.activity": e("GET", "/api/v1/projects/activity/recent", B, "live"),
  "projects.envVars": e("GET", "/api/v1/projects/{projectId}/env", B, "planned"),
  "projects.updateEnvVars": e("PUT", "/api/v1/projects/{projectId}/env", B, "planned"),
  "projects.uploads.create": e("POST", "/api/v1/projects", B, "live"),
  "projects.uploads.complete": e("POST", "/api/v1/projects/{uploadId}/uploads/complete", B, "live"),
  "projects.uploads.get": e("GET", "/api/v1/projects/{uploadId}/analysis", B, "live"),
  "projects.events": e("SSE", "/api/v1/projects/{projectId}/events", B, "planned"),
  "projects.terminal.create": e("POST", "/api/v1/projects/{projectId}/terminal", "infra", "planned"),
  "projects.diagnostics": e("GET", "/api/v1/builds?project_id={projectId}", B, "live"),
  "projects.git.log": e("GET", "/api/v1/projects/{projectId}/git/log", B, "planned"),
  // files
  "projects.files.tree": e("GET", "/api/v1/projects/{projectId}/files", B, "live"),
  "projects.files.read": e("GET", "/api/v1/projects/{projectId}/files/content?path=", B, "live"),
  "projects.files.save": e("PUT", "/api/v1/projects/{projectId}/files/content?path=", B, "live"),
  "projects.files.create": e("PUT", "/api/v1/projects/{projectId}/files/content?path=", B, "live"),
  "projects.files.move": e("POST", "/api/v1/projects/{projectId}/files/move", B, "live"),
  "projects.files.delete": e("DELETE", "/api/v1/projects/{projectId}/files?path=&recursive=true", B, "live"),
  "projects.files.search": e("GET", "/api/v1/projects/{projectId}/files/search?q=", B, "live"),
  // agent: served by the dev-only in-process bridge (apps/api .../agent_dev.py, AGENT_DEV_BRIDGE=1);
  // a real deployment answers 404 here, which screens show as "waiting for backend"
  "agent.tasks.list": e("GET", "/api/v1/agent/tasks", A, "live"),
  "agent.tasks.get": e("GET", "/api/v1/agent/tasks/{taskId}", A, "live"),
  "agent.tasks.timeline": e("GET", "/api/v1/agent/tasks/{taskId}/timeline", A, "live"),
  "agent.tasks.cancel": e("POST", "/api/v1/agent/tasks/{taskId}/cancel", A, "live"),
  "agent.tasks.events": e("SSE", "/api/v1/agent/tasks/{taskId}/events", A, "live"),
  "agent.messages.list": e("GET", "/api/v1/agent/projects/{projectId}/messages", A, "live"),
  "agent.messages.send": e("POST", "/api/v1/agent/projects/{projectId}/messages", A, "live"),
  "agent.changeSets.get": e("GET", "/api/v1/agent/change-sets/{changeSetId}", A, "live"),
  "agent.changeSets.decide": e("POST", "/api/v1/agent/change-sets/{changeSetId}/decision", A, "live"),
  // builds
  "builds.list": e("GET", "/api/v1/builds", B, "live"),
  "builds.get": e("GET", "/api/v1/builds/{buildId}", B, "live"),
  "builds.start": e("POST", "/api/v1/builds", B, "live"),
  "builds.retry": e("POST", "/api/v1/builds", B, "live"),
  "builds.cancel": e("POST", "/api/v1/builds/{buildId}/cancel", B, "live"),
  "builds.logs": e("GET", "/api/v1/builds/{buildId}/logs", B, "live"),
  "builds.logs.stream": e("SSE", "/api/v1/builds/{buildId}/logs/stream", B, "live"),
  "artifacts.list": e("GET", "/api/v1/artifacts?build_id=", B, "live"),
  "artifacts.download": e("POST", "/api/v1/artifacts/{artifactId}/download-url", B, "live"),
  // tests
  "tests.list": e("GET", "/api/v1/tests?project_id=", B, "live"),
  "tests.get": e("GET", "/api/v1/tests/{jobId}", B, "live"),
  "tests.start": e("POST", "/api/v1/tests", B, "live"),
  "tests.cases": e("GET", "/api/v1/tests/{jobId}/cases", B, "planned"),
  "tests.screenshots": e("GET", "/api/v1/tests/{jobId}/screenshots", "infra", "planned"),
  "tests.logs": e("GET", "/api/v1/tests/{jobId}/logs", B, "planned"),
  // usage / billing (tables exist, services not built)
  "usage.summary": e("GET", "/api/v1/usage/summary", B, "planned"),
  "usage.daily": e("GET", "/api/v1/usage/daily", B, "planned"),
  "billing.plans": e("GET", "/api/v1/billing/plans", B, "planned"),
  "billing.subscription": e("GET", "/api/v1/billing/subscription", B, "planned"),
  "billing.invoices": e("GET", "/api/v1/billing/invoices", B, "planned"),
  "billing.checkout": e("POST", "/api/v1/billing/checkout", B, "planned"),
  "billing.portal": e("POST", "/api/v1/billing/portal", B, "planned"),
  // admin
  "admin.overview": e("GET", "/api/v1/admin/overview", B, "live"),
  "admin.users": e("GET", "/api/v1/admin/users", B, "live"),
  "admin.workers": e("GET", "/api/v1/admin/workers", B, "live"),
  "admin.audit": e("GET", "/api/v1/admin/audit-logs", B, "live"),
  // preview / visual editor
  // live emulator preview: served by the dev-only bridge (apps/api .../preview_dev.py) when
  // AGENT_DEV_BRIDGE=1 (builds the APK locally and runs it on an emulator); a real deployment answers
  // 404, which the Preview tab shows as "the emulator service isn't connected yet"
  "preview.start": e("POST", "/api/v1/agent/projects/{projectId}/preview", A, "live"),
  "preview.stop": e("DELETE", "/api/v1/agent/projects/{projectId}/preview/{sessionId}", A, "live"),
  "ui.screens": e("GET", "/api/v1/projects/{projectId}/ui/screens", "codegen", "planned"),
  "ui.screen": e("GET", "/api/v1/projects/{projectId}/ui/screens/{screenId}", "codegen", "planned"),
  "ui.edits": e("POST", "/api/v1/projects/{projectId}/ui/screens/{screenId}/edits", "codegen", "planned"),
} as const satisfies Record<string, EndpointSpec>;

export type EndpointKey = keyof typeof ENDPOINTS;
