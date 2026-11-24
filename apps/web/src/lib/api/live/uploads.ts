/**
 * The frontend models uploads as: create session -> PUT file to a signed URL -> complete -> poll.
 * The backend validates and extracts synchronously in one multipart POST to an existing project,
 * so this module bridges the two:
 *
 *  create   -> client-side session only (nothing is created on the server yet)
 *  upload   -> POST /projects (create) then POST /projects/{id}/uploads (multipart, with progress);
 *              if the archive is rejected the just-created project is deleted again
 *  complete -> no-op (the work already happened)
 *  get      -> reads detected settings from GET /projects/{id}/analysis
 *
 * Sessions live in memory for the duration of the wizard.
 */
import type { ApkAnalysis, CreateUploadRequest, UploadSession, ZipAnalysis } from "@apppilot/contracts";
import { ApiError } from "../errors";
import { backend, refreshSession } from "./http";

export const LIVE_UPLOAD_SCHEME = "live-upload:";

interface Entry {
  session: UploadSession;
  fileName: string;
}
const sessions = new Map<string, Entry>();

const stem = (name: string) => name.replace(/\.(zip|apk)$/i, "").trim() || "Imported project";

export function createUploadSession(body: CreateUploadRequest): UploadSession {
  const id = crypto.randomUUID();
  const session: UploadSession = {
    id,
    kind: body.kind,
    status: "uploading",
    uploadUrl: `${LIVE_UPLOAD_SCHEME}${id}`,
    analysisProgress: 0,
    validationErrors: [],
    projectId: null,
    zipAnalysis: null,
    apkAnalysis: null,
  };
  sessions.set(id, { session, fileName: body.fileName });
  return { ...session };
}

function xhrUpload(path: string, file: File, onProgress: (pct: number) => void, signal?: AbortSignal): Promise<{ file_count: number }> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", path);
    xhr.withCredentials = true;
    xhr.setRequestHeader("Accept", "application/json");
    xhr.upload.onprogress = (e) => e.lengthComputable && onProgress(Math.round((e.loaded / e.total) * 100));
    xhr.onload = () => {
      let data: { error?: { code?: string; message?: string }; file_count?: number } = {};
      try {
        data = JSON.parse(xhr.responseText);
      } catch {
        /* non-JSON error page */
      }
      if (xhr.status >= 200 && xhr.status < 300) return resolve({ file_count: data.file_count ?? 0 });
      reject(
        new ApiError({
          status: xhr.status,
          code: data.error?.code ?? "http_error",
          message:
            data.error?.message ??
            (xhr.status === 413 ? "That file is too large." : `Upload failed (${xhr.status}).`),
        }),
      );
    };
    xhr.onerror = () => reject(new ApiError({ status: 0, code: "network", message: "Upload failed. Check your connection and try again.", unreachable: true }));
    xhr.onabort = () => reject(new DOMException("Upload cancelled", "AbortError"));
    signal?.addEventListener("abort", () => xhr.abort(), { once: true });
    const form = new FormData();
    form.append("file", file, file.name);
    xhr.send(form);
  });
}

export async function runUpload(sessionId: string, file: File, onProgress: (pct: number) => void, signal?: AbortSignal): Promise<void> {
  const entry = sessions.get(sessionId);
  if (!entry) throw new ApiError({ status: 404, code: "not_found", message: "Upload session not found." });
  const { session } = entry;
  // A cheap authenticated call first: refreshes an expired access cookie (XHR can't retry transparently).
  await backend("GET", "/api/v1/auth/session", { key: "auth.session" }).catch(async (e) => {
    if (e instanceof ApiError && e.status === 401 && (await refreshSession())) return;
    throw e;
  });
  const project = await backend<{ id: string }>("POST", "/api/v1/projects", {
    key: "projects.uploads.create",
    body: { name: stem(entry.fileName).slice(0, 120), description: `Imported from ${entry.fileName}` },
  });
  try {
    const result = await xhrUpload(`/api/v1/projects/${project.id}/uploads`, file, onProgress, signal);
    session.projectId = project.id;
    session.status = "analyzing";
    if (session.kind === "apk") {
      session.apkAnalysis = apkSummary(file.size, result.file_count);
      session.status = "ready";
      session.analysisProgress = 100;
    }
  } catch (e) {
    // Rejected or cancelled: leave no empty project behind.
    await backend("DELETE", `/api/v1/projects/${project.id}`, { key: "projects.delete" }).catch(() => undefined);
    session.status = "failed";
    session.validationErrors = [e instanceof Error ? e.message : "Upload failed."];
    throw e;
  }
}

function apkSummary(sizeBytes: number, entries: number): ApkAnalysis {
  return {
    packageName: null,
    versionName: null,
    versionCode: null,
    minSdk: null,
    targetSdk: null,
    sizeBytes,
    permissions: [],
    activities: [],
    services: [],
    receivers: [],
    nativeAbis: [],
    detectedLibraries: [],
    obfuscated: null,
    findings: [
      {
        severity: "info",
        message: `The APK passed structural validation (${entries.toLocaleString()} entries) and is stored. Its manifest, permissions and libraries are not extracted yet.`,
      },
    ],
  };
}

interface BAnalysis {
  detected: { agp: string | null; kotlin: string | null; has_wrapper: boolean; plugins: string[]; notes: string[] };
  required: { problems: string[]; warnings: string[] };
  file_count: number;
  modules: string[];
  build_system: ZipAnalysis["buildSystem"];
}

export async function getUploadSession(id: string): Promise<UploadSession> {
  const entry = sessions.get(id);
  if (!entry) throw new ApiError({ status: 404, code: "not_found", message: "Upload session not found." });
  const s = entry.session;
  if (s.kind === "android_zip" && s.status === "analyzing" && s.projectId) {
    const a = await backend<BAnalysis>("GET", `/api/v1/projects/${s.projectId}/analysis`, { key: "projects.uploads.get" });
    s.zipAnalysis = {
      gradleWrapper: a.detected.has_wrapper,
      buildSystem: a.build_system,
      modules: a.modules,
      language: a.detected.kotlin ? "kotlin" : "java",
      uiToolkit: a.detected.plugins.includes("compose") ? "compose" : "xml",
      agpVersion: a.detected.agp,
      kotlinVersion: a.detected.kotlin,
      fileCount: a.file_count,
      // Problems mean the project can't be built as-is; surface them without rejecting the import.
      warnings: [...a.required.problems, ...a.required.warnings],
    };
    s.status = "ready";
    s.analysisProgress = 100;
  }
  return { ...s, validationErrors: [...s.validationErrors] };
}
