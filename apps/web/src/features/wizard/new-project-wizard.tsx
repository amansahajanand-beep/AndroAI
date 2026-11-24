"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import type { ApkAnalysis, ProjectLanguage, UiToolkit, UploadKind, UploadSession, ZipAnalysis } from "@apppilot/contracts";
import {
  AlertTriangle,
  ArrowLeft,
  CheckCircle2,
  FileArchive,
  Info,
  Loader2,
  MessageSquareText,
  Package,
  Plus,
  ShieldAlert,
  X,
  XCircle,
} from "lucide-react";
import { toast } from "sonner";
import { PageBody, PageHeader } from "@/components/layout/page";
import { Button } from "@/components/ui/button";
import { Segmented } from "@/components/ui/overlays";
import { Alert, Badge, Card, CardContent, Field, Input, Progress, Textarea } from "@/components/ui/primitives";
import { api } from "@/lib/api/client";
import { errorMessage, isPendingBackend } from "@/lib/api/errors";
import { useCreateProject, usePreferences, useUpload } from "@/lib/api/hooks";
import { uploadToSignedUrl } from "@/lib/api/upload";
import { MAX_APK_BYTES, MAX_ZIP_BYTES } from "@/lib/env";
import { cn, formatBytes } from "@/lib/utils";
import { UploadDropzone } from "./upload-dropzone";

type Method = "prompt" | "zip" | "apk";

const METHODS: { id: Method; title: string; body: string; icon: typeof Package }[] = [
  { id: "prompt", title: "Describe a new app", body: "The agent generates a Gradle project from your description.", icon: MessageSquareText },
  { id: "zip", title: "Upload an Android Studio project", body: "Bring your existing source as a .zip and keep working on it.", icon: FileArchive },
  { id: "apk", title: "Analyze an APK", body: "Inspect a compiled app. This doesn't give you its original source.", icon: Package },
];

const PACKAGE_RE = /^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$/;

/* ---------------- A. Prompt ---------------- */

function PromptForm({ initialDescription }: { initialDescription: string }) {
  const router = useRouter();
  const create = useCreateProject();
  const prefs = usePreferences();
  const [name, setName] = useState("");
  const [description, setDescription] = useState(initialDescription);
  const [requirements, setRequirements] = useState<string[]>([""]);
  const [language, setLanguage] = useState<ProjectLanguage>("kotlin");
  const [toolkit, setToolkit] = useState<UiToolkit>("compose");
  const [packageName, setPackageName] = useState("");
  const [minSdk, setMinSdk] = useState("26");
  const [targetSdk, setTargetSdk] = useState("35");
  const [config, setConfig] = useState<{ key: string; value: string }[]>([]);
  const [errors, setErrors] = useState<Record<string, string | undefined>>({});
  const appliedPrefs = useRef(false);

  // Seed language/toolkit from the user's defaults once they load.
  useEffect(() => {
    if (prefs.data && !appliedPrefs.current) {
      appliedPrefs.current = true;
      setLanguage(prefs.data.defaultLanguage);
      setToolkit(prefs.data.defaultUiToolkit);
    }
  }, [prefs.data]);

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const min = Number(minSdk);
    const target = Number(targetSdk);
    const next = {
      name: !name.trim() ? "Give the app a name." : undefined,
      description: description.trim().length < 20 ? "Describe the app in at least a sentence (20+ characters)." : undefined,
      packageName: packageName && !PACKAGE_RE.test(packageName) ? "Use a lowercase dotted name like com.example.app." : undefined,
      minSdk: !Number.isInteger(min) || min < 21 || min > 36 ? "Use an API level between 21 and 36." : undefined,
      targetSdk: !Number.isInteger(target) || target < min || target > 36 ? "Must be at least the minimum SDK and at most 36." : undefined,
    };
    setErrors(next);
    if (Object.values(next).some(Boolean)) return;
    create.mutate(
      {
        name: name.trim(),
        description: description.trim(),
        requirements: requirements.map((r) => r.trim()).filter(Boolean),
        language,
        uiToolkit: toolkit,
        packageName: packageName || undefined,
        minSdk: min,
        targetSdk: target,
        config: Object.fromEntries(config.filter((c) => c.key.trim()).map((c) => [c.key.trim(), c.value])),
      },
      {
        onSuccess: ({ project, taskId }) => {
          toast.success(`Generating ${project.name}`);
          router.push(taskId ? `/projects/${project.id}/agent?task=${taskId}` : `/projects/${project.id}/ide`);
        },
      },
    );
  };

  return (
    <form onSubmit={submit} noValidate className="grid gap-5">
      {create.error ? (
        <Alert tone="danger" role="alert">
          <XCircle />
          <span>{isPendingBackend(create.error) ? "Project generation isn't available yet — the backend endpoint is pending." : errorMessage(create.error)}</span>
        </Alert>
      ) : null}
      <Field label="App name" htmlFor="name" error={errors.name}>
        <Input id="name" value={name} onChange={(e) => setName(e.target.value)} placeholder="Pantry Pal" aria-invalid={!!errors.name} autoFocus />
      </Field>
      <Field label="What should the app do?" htmlFor="description" error={errors.description} hint="Describe who it's for and the main screens. The agent turns this into a plan you can follow.">
        <Textarea id="description" value={description} onChange={(e) => setDescription(e.target.value)} className="min-h-28" placeholder="A grocery list app where a household shares lists, scans barcodes to add items, and gets a reminder when near a saved store." aria-invalid={!!errors.description} />
      </Field>

      <fieldset className="grid gap-2">
        <legend className="mb-1.5 text-[14px] font-medium">Requirements</legend>
        <p className="-mt-1 text-[13px] text-muted-foreground">Specific must-haves, one per line: libraries, screens, behaviours.</p>
        {requirements.map((r, i) => (
          <div key={i} className="flex gap-2">
            <Input
              aria-label={`Requirement ${i + 1}`}
              value={r}
              placeholder={i === 0 ? "Use Room for local storage" : ""}
              onChange={(e) => setRequirements((rs) => rs.map((x, j) => (j === i ? e.target.value : x)))}
            />
            <Button type="button" variant="subtle" size="icon" aria-label={`Remove requirement ${i + 1}`} onClick={() => setRequirements((rs) => (rs.length === 1 ? [""] : rs.filter((_, j) => j !== i)))}>
              <X />
            </Button>
          </div>
        ))}
        <Button type="button" variant="ghost" size="sm" className="justify-self-start" onClick={() => setRequirements((rs) => [...rs, ""])}>
          <Plus /> Add requirement
        </Button>
      </fieldset>

      <div className="grid gap-5 sm:grid-cols-2">
        <div className="grid gap-1.5">
          <span className="text-[14px] font-medium">Language</span>
          <Segmented<ProjectLanguage> aria-label="Language" value={language} onChange={setLanguage} options={[{ value: "kotlin", label: "Kotlin" }, { value: "java", label: "Java" }]} />
        </div>
        <div className="grid gap-1.5">
          <span className="text-[14px] font-medium">UI toolkit</span>
          <Segmented<UiToolkit> aria-label="UI toolkit" value={toolkit} onChange={setToolkit} options={[{ value: "compose", label: "Jetpack Compose" }, { value: "xml", label: "XML views" }]} />
          {language === "java" && toolkit === "compose" ? (
            <p className="text-[13px] text-warning">Compose requires Kotlin for UI code. The agent will write UI in Kotlin and the rest in Java.</p>
          ) : null}
        </div>
      </div>

      <details className="group rounded-md border border-border">
        <summary className="cursor-pointer select-none px-3 py-2 text-[14px] font-medium">Additional configuration</summary>
        <div className="grid gap-4 border-t border-border p-3">
          <div className="grid gap-4 sm:grid-cols-3">
            <Field label="Package name" htmlFor="pkg" error={errors.packageName} hint="Optional" className="sm:col-span-3">
              <Input id="pkg" value={packageName} onChange={(e) => setPackageName(e.target.value)} placeholder="app.pantrypal" className="font-mono" aria-invalid={!!errors.packageName} />
            </Field>
            <Field label="Min SDK" htmlFor="min" error={errors.minSdk}>
              <Input id="min" inputMode="numeric" value={minSdk} onChange={(e) => setMinSdk(e.target.value)} aria-invalid={!!errors.minSdk} />
            </Field>
            <Field label="Target SDK" htmlFor="target" error={errors.targetSdk}>
              <Input id="target" inputMode="numeric" value={targetSdk} onChange={(e) => setTargetSdk(e.target.value)} aria-invalid={!!errors.targetSdk} />
            </Field>
          </div>
          <div className="grid gap-2">
            <span className="text-[14px] font-medium">Extra settings</span>
            {config.map((c, i) => (
              <div key={i} className="flex gap-2">
                <Input aria-label="Setting name" placeholder="navigation" value={c.key} className="font-mono" onChange={(e) => setConfig((cs) => cs.map((x, j) => (j === i ? { ...x, key: e.target.value } : x)))} />
                <Input aria-label="Setting value" placeholder="compose-navigation" value={c.value} onChange={(e) => setConfig((cs) => cs.map((x, j) => (j === i ? { ...x, value: e.target.value } : x)))} />
                <Button type="button" variant="subtle" size="icon" aria-label="Remove setting" onClick={() => setConfig((cs) => cs.filter((_, j) => j !== i))}>
                  <X />
                </Button>
              </div>
            ))}
            <Button type="button" variant="ghost" size="sm" className="justify-self-start" onClick={() => setConfig((cs) => [...cs, { key: "", value: "" }])}>
              <Plus /> Add setting
            </Button>
          </div>
        </div>
      </details>

      <div className="flex justify-end">
        <Button type="submit" size="lg" variant="ai" loading={create.isPending}>
          Generate project
        </Button>
      </div>
    </form>
  );
}

/* ---------------- B/C. Uploads ---------------- */

type Phase = "idle" | "uploading" | "processing" | "error";

function useUploadFlow(kind: UploadKind) {
  const [phase, setPhase] = useState<Phase>("idle");
  const [file, setFile] = useState<File | null>(null);
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState<unknown>(null);
  const [uploadId, setUploadId] = useState<string | null>(null);
  const abort = useRef<AbortController | null>(null);
  const session = useUpload(uploadId);

  const start = async (f: File) => {
    setFile(f);
    setError(null);
    setProgress(0);
    setPhase("uploading");
    abort.current = new AbortController();
    try {
      const s = await api.projects.createUpload({ kind, fileName: f.name, sizeBytes: f.size });
      await uploadToSignedUrl(s.uploadUrl, f, setProgress, abort.current.signal);
      await api.projects.completeUpload(s.id);
      setUploadId(s.id);
      setPhase("processing");
    } catch (e) {
      if (e instanceof DOMException && e.name === "AbortError") {
        setPhase("idle");
        setFile(null);
        return;
      }
      setError(e);
      setPhase("error");
    }
  };

  const reset = () => {
    abort.current?.abort();
    setPhase("idle");
    setFile(null);
    setUploadId(null);
    setError(null);
  };

  return { phase, file, progress, error, session: session.data, sessionError: session.error, start, reset, cancel: () => abort.current?.abort() };
}

function StepLine({ state, label, detail }: { state: "done" | "active" | "todo" | "failed"; label: string; detail?: React.ReactNode }) {
  return (
    <li className="flex gap-3">
      <span className="mt-0.5">
        {state === "done" ? <CheckCircle2 className="size-4 text-success" aria-label="Done" /> : state === "active" ? <Loader2 className="size-4 animate-spin text-primary" aria-label="In progress" /> : state === "failed" ? <XCircle className="size-4 text-destructive" aria-label="Failed" /> : <span className="block size-4 rounded-full border border-border-strong" aria-label="Not started" />}
      </span>
      <div className="min-w-0 flex-1">
        <p className={cn("text-[14px]", state === "todo" && "text-muted-foreground")}>{label}</p>
        {detail}
      </div>
    </li>
  );
}

function UploadProgress({ flow }: { flow: ReturnType<typeof useUploadFlow> }) {
  const s = flow.session;
  const failed = s?.status === "failed" || flow.phase === "error";
  const uploadState = flow.phase === "uploading" ? "active" : flow.phase === "error" && !s ? "failed" : "done";
  const validateState: "done" | "active" | "todo" | "failed" = !s ? "todo" : s.status === "validating" ? "active" : s.status === "failed" ? "failed" : "done";
  const analyzeState: "done" | "active" | "todo" | "failed" = !s || s.status === "validating" || s.status === "failed" ? "todo" : s.status === "analyzing" ? "active" : "done";

  return (
    <div className="grid gap-4">
      <div className="flex items-center justify-between gap-2 rounded-md border border-border px-3 py-2">
        <span className="truncate font-mono text-[14px]">{flow.file?.name}</span>
        <span className="shrink-0 text-[13px] text-muted-foreground">{formatBytes(flow.file?.size)}</span>
      </div>
      <ol className="grid gap-3">
        <StepLine
          state={uploadState}
          label="Upload"
          detail={flow.phase === "uploading" ? (
            <div className="mt-1.5 flex items-center gap-2">
              <Progress value={flow.progress} label="Upload progress" className="flex-1" />
              <span className="w-9 text-right text-[13px] tabular-nums text-muted-foreground">{flow.progress}%</span>
            </div>
          ) : null}
        />
        <StepLine
          state={validateState}
          label="Validate file"
          detail={s?.validationErrors.length ? (
            <ul className="mt-1 list-disc pl-4 text-[13px] text-destructive">
              {s.validationErrors.map((e) => <li key={e}>{e}</li>)}
            </ul>
          ) : null}
        />
        <StepLine
          state={analyzeState}
          label="Analyze"
          detail={s?.status === "analyzing" ? (
            <div className="mt-1.5 flex items-center gap-2">
              <Progress value={s.analysisProgress} tone="ai" label="Analysis progress" className="flex-1" />
              <span className="w-9 text-right text-[13px] tabular-nums text-muted-foreground">{s.analysisProgress}%</span>
            </div>
          ) : null}
        />
      </ol>
      {flow.phase === "error" ? (
        <Alert tone="danger" role="alert">
          <XCircle />
          <span>{isPendingBackend(flow.error) ? "Uploads aren't available yet — the upload endpoint is pending on the backend." : errorMessage(flow.error)}</span>
        </Alert>
      ) : null}
      <div className="flex gap-2">
        {flow.phase === "uploading" ? <Button variant="outline" onClick={flow.cancel}>Cancel upload</Button> : null}
        {failed ? <Button variant="outline" onClick={flow.reset}>Choose another file</Button> : null}
      </div>
    </div>
  );
}

function ZipReport({ a, projectId }: { a: ZipAnalysis; projectId: string | null }) {
  const rows: [string, React.ReactNode][] = [
    ["Build system", a.buildSystem === "gradle-kts" ? "Gradle (Kotlin DSL)" : a.buildSystem === "gradle-groovy" ? "Gradle (Groovy)" : "Unknown"],
    ["Gradle wrapper", a.gradleWrapper ? "Included" : "Missing — builds will use the platform's Gradle"],
    ["Modules", <span key="m" className="font-mono">{a.modules.join(", ")}</span>],
    ["Language", a.language],
    ["UI toolkit", a.uiToolkit === "xml" ? "XML views" : a.uiToolkit === "compose" ? "Jetpack Compose" : "Mixed"],
    ["Android Gradle Plugin", a.agpVersion ?? "Not detected"],
    ["Kotlin", a.kotlinVersion ?? "Not detected"],
    ["Files", a.fileCount.toLocaleString()],
  ];
  return (
    <div className="grid gap-4">
      <Alert tone="success"><CheckCircle2 /><span>Project imported. You can open it in the IDE or ask the agent for a change.</span></Alert>
      <dl className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-2 text-[14px]">
        {rows.map(([k, v]) => (
          <div key={k} className="contents">
            <dt className="text-muted-foreground">{k}</dt>
            <dd>{v}</dd>
          </div>
        ))}
      </dl>
      {a.warnings.length ? (
        <Alert tone="warning"><AlertTriangle /><ul className="list-disc pl-4">{a.warnings.map((w) => <li key={w}>{w}</li>)}</ul></Alert>
      ) : null}
      {projectId ? (
        <div className="flex flex-wrap gap-2">
          <Button asChild><Link href={`/projects/${projectId}/ide`}>Open in IDE</Link></Button>
          <Button asChild variant="outline"><Link href={`/projects/${projectId}/ide?assistant=modify`}>Describe a change</Link></Button>
        </div>
      ) : null}
    </div>
  );
}

const FINDING_TONE = { info: "info", warning: "warning", risk: "danger" } as const;
const FINDING_ICON = { info: Info, warning: AlertTriangle, risk: ShieldAlert } as const;

function ApkReport({ a, projectId }: { a: ApkAnalysis; projectId: string | null }) {
  const list = (items: string[]) =>
    items.length ? (
      <ul className="grid gap-0.5 font-mono text-[13px]">{items.map((i) => <li key={i} className="truncate" title={i}>{i}</li>)}</ul>
    ) : (
      <span className="text-muted-foreground">None</span>
    );
  return (
    <div className="grid gap-5">
      <dl className="grid grid-cols-2 gap-x-6 gap-y-3 text-[14px] sm:grid-cols-4">
        {[
          ["Package", <span key="p" className="font-mono">{a.packageName}</span>],
          ["Version", `${a.versionName ?? "—"} (${a.versionCode ?? "—"})`],
          ["SDK", `min ${a.minSdk ?? "—"} · target ${a.targetSdk ?? "—"}`],
          ["Size", formatBytes(a.sizeBytes)],
        ].map(([k, v]) => (
          <div key={String(k)}>
            <dt className="text-[13px] text-muted-foreground">{k}</dt>
            <dd className="mt-0.5">{v}</dd>
          </div>
        ))}
      </dl>
      {a.findings.length ? (
        <div className="grid gap-2">
          <h3 className="text-[14px] font-semibold">Findings</h3>
          {a.findings.map((f) => {
            const Icon = FINDING_ICON[f.severity];
            return <Alert key={f.message} tone={FINDING_TONE[f.severity]}><Icon /><span>{f.message}</span></Alert>;
          })}
        </div>
      ) : null}
      <div className="grid gap-4 sm:grid-cols-2">
        <section><h3 className="mb-1.5 text-[14px] font-semibold">Permissions ({a.permissions.length})</h3>{list(a.permissions)}</section>
        <section><h3 className="mb-1.5 text-[14px] font-semibold">Activities ({a.activities.length})</h3>{list(a.activities)}</section>
        <section><h3 className="mb-1.5 text-[14px] font-semibold">Services and receivers</h3>{list([...a.services, ...a.receivers])}</section>
        <section>
          <h3 className="mb-1.5 text-[14px] font-semibold">Libraries and native code</h3>
          {list(a.detectedLibraries)}
          <p className="mt-1.5 text-[13px] text-muted-foreground">ABIs: {a.nativeAbis.join(", ") || "none"} · {a.obfuscated === null ? "Obfuscation not analysed" : a.obfuscated ? "Obfuscated" : "Not obfuscated"}</p>
        </section>
      </div>
      {projectId ? (
        <div className="flex flex-wrap gap-2">
          <Button asChild><Link href={`/projects/${projectId}/ide`}>Browse decompiled files</Link></Button>
        </div>
      ) : null}
    </div>
  );
}

function UploadPanel({ kind }: { kind: UploadKind }) {
  const flow = useUploadFlow(kind);
  const s: UploadSession | undefined = flow.session;
  const isApk = kind === "apk";

  return (
    <div className="grid gap-5">
      {isApk ? (
        <Alert tone="warning">
          <Info />
          <span>
            <strong className="font-medium">APK analysis is not source access.</strong> We inspect the compiled app —
            manifest, permissions, components, libraries — and can show decompiled code. It won&apos;t recover the
            original project, and changes the agent makes produce new code rather than editing the original.
          </span>
        </Alert>
      ) : null}
      {flow.phase === "idle" ? (
        <UploadDropzone
          accept={isApk ? ".apk,application/vnd.android.package-archive" : ".zip,application/zip"}
          extension={isApk ? ".apk" : ".zip"}
          maxBytes={isApk ? MAX_APK_BYTES : MAX_ZIP_BYTES}
          onFile={flow.start}
          hint={isApk ? `Up to ${formatBytes(MAX_APK_BYTES, 0)}.` : `The folder that contains settings.gradle(.kts). Up to ${formatBytes(MAX_ZIP_BYTES, 0)}. Leave out build/ folders and local.properties.`}
        />
      ) : s?.status === "ready" ? (
        s.apkAnalysis ? <ApkReport a={s.apkAnalysis} projectId={s.projectId} /> : s.zipAnalysis ? <ZipReport a={s.zipAnalysis} projectId={s.projectId} /> : null
      ) : (
        <UploadProgress flow={flow} />
      )}
    </div>
  );
}

/* ---------------- Wizard ---------------- */

export function NewProjectWizard() {
  const params = useSearchParams();
  const router = useRouter();
  const initial = params.get("method");
  const method: Method | null = initial === "prompt" || initial === "zip" || initial === "apk" ? initial : null;
  const setMethod = (m: Method | null) => router.replace(m ? `/projects/new?method=${m}` : "/projects/new", { scroll: false });
  const current = METHODS.find((m) => m.id === method);

  return (
    <PageBody className="max-w-3xl">
      <PageHeader
        title={current ? current.title : "New project"}
        description={current ? current.body : "Choose how you want to start."}
        actions={
          current ? (
            <Button variant="ghost" size="sm" onClick={() => setMethod(null)}>
              <ArrowLeft /> Change method
            </Button>
          ) : null
        }
      />
      {!current ? (
        <div className="grid gap-3" role="list">
          {METHODS.map((m) => (
            <button
              key={m.id}
              role="listitem"
              onClick={() => setMethod(m.id)}
              className="group flex items-start gap-4 rounded-xl border border-border bg-card p-5 text-left shadow-card transition-all duration-300 hover:-translate-y-0.5 hover:border-primary/50 hover:shadow-pop"
            >
              <span className={cn("grid size-11 shrink-0 place-items-center rounded-xl ring-1 transition-transform duration-300 group-hover:scale-110", m.id === "prompt" ? "bg-ai-soft text-ai ring-ai/25" : "bg-primary-soft text-primary ring-primary/25")}>
                <m.icon className="size-5" aria-hidden />
              </span>
              <span>
                <span className="flex items-center gap-2 text-base font-semibold">
                  {m.title}
                  {m.id === "apk" ? <Badge tone="warning">Analysis only</Badge> : null}
                </span>
                <span className="mt-1 block text-[14px] text-muted-foreground">{m.body}</span>
              </span>
            </button>
          ))}
        </div>
      ) : (
        <Card>
          <CardContent className="p-5">
            {method === "prompt" ? <PromptForm initialDescription={params.get("description") ?? ""} /> : <UploadPanel key={method} kind={method === "apk" ? "apk" : "android_zip"} />}
          </CardContent>
        </Card>
      )}
    </PageBody>
  );
}
