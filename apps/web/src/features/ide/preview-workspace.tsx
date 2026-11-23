"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import type { EmulatorStreamSession, PreviewDevice, PreviewErrorCode, UiScreen } from "@apppilot/contracts";
import { AlertTriangle, ExternalLink, FlaskConical, Hammer, Loader2, RefreshCw, Smartphone } from "lucide-react";
import { toast } from "sonner";
import { EmptyState } from "@/components/states/states";
import { Button } from "@/components/ui/button";
import { Tooltip } from "@/components/ui/overlays";
import { api } from "@/lib/api/client";
import { ApiError, errorMessage, isPendingBackend } from "@/lib/api/errors";
import { useBuildActions, useEmulatorSession, useUiScreens } from "@/lib/api/hooks";
import { IS_MOCK } from "@/lib/env";
import { cn } from "@/lib/utils";
import { useIdeStore } from "@/stores/ide-store";

/* ------------------------------------------------------------------ */
/* Helpers                                                             */
/* ------------------------------------------------------------------ */

const DEFAULT_DEVICE: PreviewDevice = { name: "Pixel 8", apiLevel: 34, width: 1080, height: 2400 };

/** Only embed https, loopback http, same-origin paths and image data URLs. Anything else is refused. */
export function isSafePreviewUrl(raw: string, opts?: { allowDataImage?: boolean }): boolean {
  if (raw.startsWith("/") && !raw.startsWith("//")) return true;
  if (opts?.allowDataImage && /^data:image\/(png|jpe?g|webp|gif|svg\+xml)[;,]/i.test(raw)) return true;
  try {
    const u = new URL(raw);
    if (u.protocol === "https:") return true;
    return u.protocol === "http:" && (u.hostname === "localhost" || u.hostname === "127.0.0.1");
  } catch {
    return false;
  }
}

type Reason = "pending" | PreviewErrorCode | "error";
const KNOWN: readonly string[] = ["no_build", "build_failed", "build_in_progress", "emulator_unavailable", "unsupported_project"];

function reasonOf(err: unknown): Reason {
  if (isPendingBackend(err)) return "pending";
  if (err instanceof ApiError && KNOWN.includes(err.code)) return err.code as PreviewErrorCode;
  return "error";
}

const SHORT_REASON: Record<Reason, string> = {
  pending: "the emulator service isn't connected yet",
  no_build: "nothing has been built yet",
  build_failed: "the latest build failed",
  build_in_progress: "a build is still running",
  emulator_unavailable: "no emulator is free right now",
  unsupported_project: "this project can't be previewed",
  error: "the emulator couldn't start",
};

/* ------------------------------------------------------------------ */
/* Visual building blocks                                              */
/* ------------------------------------------------------------------ */

type ChipTone = "live" | "screens" | "demo" | "idle";

function SourceChip({ tone, children }: { tone: ChipTone; children: React.ReactNode }) {
  const styles: Record<ChipTone, string> = {
    live: "bg-success-soft text-success",
    screens: "bg-primary-soft text-primary",
    demo: "bg-warning-soft text-warning",
    idle: "bg-surface-3 text-muted-foreground",
  };
  return (
    <span className={cn("inline-flex h-6 shrink-0 items-center gap-1.5 rounded-full px-2.5 text-[12px] font-medium", styles[tone])}>
      <span className={cn("size-1.5 rounded-full bg-current", tone === "live" && "animate-glow")} aria-hidden />
      {children}
    </span>
  );
}

/** A phone bezel that scales to the available height and keeps the device's aspect ratio. */
function PhoneFrame({ device, children, label }: { device?: PreviewDevice; children: React.ReactNode; label?: string }) {
  const d = device ?? DEFAULT_DEVICE;
  return (
    <div className="flex h-full min-h-0 items-center justify-center p-5">
      <div
        className="relative h-full max-h-[800px] min-h-[320px] rounded-[2.4rem] bg-[#0b0a14] p-[7px] shadow-pop ring-1 ring-foreground/15"
        style={{ aspectRatio: `${d.width} / ${d.height}` }}
        aria-label={label}
      >
        <div className="relative size-full overflow-hidden rounded-[2rem] bg-background">{children}</div>
        <span aria-hidden className="pointer-events-none absolute left-1/2 top-[13px] size-3 -translate-x-1/2 rounded-full bg-[#0b0a14] ring-1 ring-white/10" />
      </div>
    </div>
  );
}

function Stage({ children }: { children: React.ReactNode }) {
  return (
    <div className="relative min-h-0 flex-1 overflow-hidden bg-surface-2/50">
      <div
        aria-hidden
        className="absolute inset-0"
        style={{ backgroundImage: "radial-gradient(60% 55% at 50% 0%, color-mix(in oklab, var(--brand-1) 16%, transparent), transparent 70%)" }}
      />
      <div aria-hidden className="dot-grid absolute inset-0 opacity-40 [mask-image:radial-gradient(ellipse_70%_70%_at_50%_40%,black,transparent)]" />
      <div className="relative size-full">{children}</div>
    </div>
  );
}

function Notice({ tone = "info", children }: { tone?: "info" | "demo"; children: React.ReactNode }) {
  return (
    <div
      className={cn(
        "mx-auto flex max-w-xl items-start gap-2 rounded-lg border px-3 py-2 text-[13px] leading-snug",
        tone === "demo" ? "border-warning/30 bg-warning-soft text-foreground" : "border-border bg-card text-muted-foreground",
      )}
      role={tone === "demo" ? "note" : undefined}
    >
      {tone === "demo" ? <FlaskConical className="mt-0.5 size-4 shrink-0 text-warning" aria-hidden /> : null}
      <span>{children}</span>
    </div>
  );
}

function Loading({ title, hint }: { title: string; hint?: string }) {
  return (
    <div className="grid size-full place-items-center" aria-busy="true">
      <div className="text-center">
        <Loader2 className="mx-auto size-6 animate-spin text-primary" aria-hidden />
        <p className="mt-3 text-[14px] font-medium">{title}</p>
        {hint ? <p className="mt-1 text-[13px] text-muted-foreground">{hint}</p> : null}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Source 1: emulator stream                                           */
/* ------------------------------------------------------------------ */

function EmulatorViewer({ session, onExpired }: { session: EmulatorStreamSession; onExpired: () => void }) {
  const [loaded, setLoaded] = useState(false);
  const [expired, setExpired] = useState(false);

  // The backend decides when the session ends; stop showing a dead stream.
  useEffect(() => {
    const ms = Date.parse(session.expiresAt) - Date.now();
    if (!Number.isFinite(ms)) return;
    // A timer (even at 0ms) keeps setState out of the effect body.
    const t = setTimeout(() => setExpired(true), Math.min(Math.max(ms, 0), 2 ** 31 - 1));
    return () => clearTimeout(t);
  }, [session.expiresAt]);

  return (
    <PhoneFrame device={session.device} label={`Live preview on ${session.device.name}`}>
      <iframe
        title={`Live app preview on ${session.device.name}`}
        src={session.viewerUrl}
        sandbox="allow-scripts allow-same-origin allow-forms allow-pointer-lock"
        referrerPolicy="no-referrer"
        onLoad={() => setLoaded(true)}
        className={cn("size-full border-0 bg-black transition-opacity duration-300", loaded && !expired ? "opacity-100" : "opacity-0")}
      />
      {!loaded && !expired ? (
        <div className="absolute inset-0 grid place-items-center bg-background">
          <Loading title={session.state === "starting" ? "Starting the emulator…" : "Connecting to the emulator…"} hint="Installing your latest build" />
        </div>
      ) : null}
      {expired ? (
        <div className="absolute inset-0 grid place-items-center bg-background/95 p-6 text-center">
          <div>
            <p className="text-[14px] font-medium">Preview session ended</p>
            <p className="mt-1 text-[13px] text-muted-foreground">Emulator sessions are time-limited to free up capacity.</p>
            <Button size="sm" className="mt-4" onClick={onExpired}>
              <RefreshCw /> Start a new session
            </Button>
          </div>
        </div>
      ) : null}
    </PhoneFrame>
  );
}

/* ------------------------------------------------------------------ */
/* Source 2: rendered screens                                          */
/* ------------------------------------------------------------------ */

function ScreensViewer({ screens, why, index, onSelect }: { screens: UiScreen[]; why: string; index: number; onSelect: (i: number) => void }) {
  const current = screens[index] ?? screens[0]!;
  return (
    <div className="flex size-full min-h-0 flex-col">
      <div className="px-4 pt-3">
        <Notice>
          Showing <strong className="font-medium text-foreground">rendered screens</strong> (still images made from your source, not a running
          app) because {why}.
        </Notice>
      </div>
      <div className="min-h-0 flex-1">
        <PhoneFrame label={`Rendered preview of ${current.name}`}>
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={current.previewUrl!} alt={`Rendered preview of ${current.name}`} className="size-full object-cover object-top" />
        </PhoneFrame>
      </div>
      {screens.length > 1 ? (
        <div className="flex justify-center gap-1.5 overflow-x-auto px-4 pb-3" role="group" aria-label="Screens">
          {screens.map((s, i) => (
            <button
              key={s.id}
              type="button"
              aria-pressed={i === index}
              onClick={() => onSelect(i)}
              className={cn(
                "h-7 shrink-0 rounded-full border px-3 text-[13px] transition-colors",
                i === index ? "border-primary/40 bg-primary-soft text-foreground" : "border-border text-muted-foreground hover:text-foreground",
              )}
            >
              {s.name}
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Source 3: nothing real available                                    */
/* ------------------------------------------------------------------ */

/** A generic sample screen. It never shows the user's project name or code: it is not their app. */
function DemoScreen() {
  const rows: [string, string][] = [
    ["Morning routine", "6 tasks"],
    ["Weekly review", "Due Friday"],
    ["Reading list", "12 items"],
  ];
  return (
    <div className="flex size-full flex-col bg-background text-foreground">
      <div className="flex items-center justify-between px-5 pb-1 pt-3 text-[11px] text-muted-foreground" aria-hidden>
        <span>9:41</span>
        <span>●●●</span>
      </div>
      <div className="px-5 pb-3 pt-2">
        <p className="font-display text-[22px] font-semibold tracking-tight">Sample app</p>
        <p className="text-[12.5px] text-muted-foreground">Demo screen</p>
      </div>
      <div className="grid gap-2.5 px-4">
        {rows.map(([t, s], i) => (
          <div key={t} className="flex items-center gap-3 rounded-2xl border border-border bg-card p-3">
            <span className={cn("grid size-9 place-items-center rounded-xl text-[12px] font-semibold", i === 0 ? "bg-brand text-white" : "bg-primary-soft text-primary")}>{t[0]}</span>
            <span className="min-w-0">
              <span className="block truncate text-[14px] font-medium">{t}</span>
              <span className="block text-[12px] text-muted-foreground">{s}</span>
            </span>
          </div>
        ))}
      </div>
      <div className="mt-auto flex items-center justify-between border-t border-border px-6 py-3" aria-hidden>
        {["Home", "Search", "Profile"].map((l, i) => (
          <span key={l} className={cn("text-[11px]", i === 0 ? "font-medium text-primary" : "text-subtle-foreground")}>{l}</span>
        ))}
      </div>
      <span aria-hidden className="absolute bottom-16 right-5 grid size-12 place-items-center rounded-2xl bg-brand text-xl text-white shadow-[0_10px_24px_-10px_var(--brand-glow)]">+</span>
      <span className="absolute right-5 top-[3.1rem] rounded-full bg-warning px-2 py-0.5 text-[10.5px] font-semibold uppercase tracking-wider text-black">Demo</span>
    </div>
  );
}

function DemoPreview() {
  return (
    <div className="flex size-full min-h-0 flex-col">
      <div className="px-4 pt-3">
        <Notice tone="demo">
          <strong className="font-medium">Demo preview.</strong> This is a generic sample screen so you can try the Preview workspace. It is{" "}
          <strong className="font-medium">not your app</strong>. Your real app appears here once the emulator or screen-render service is connected.
        </Notice>
      </div>
      <div className="min-h-0 flex-1">
        <PhoneFrame label="Demo preview, not your app">
          <DemoScreen />
        </PhoneFrame>
      </div>
    </div>
  );
}

function Unavailable({ projectId, reason, error, onRetry }: { projectId: string; reason: Reason; error: unknown; onRetry: () => void }) {
  const { start } = useBuildActions(projectId);
  const setBottomTab = useIdeStore((s) => s.setBottomTab);
  const setView = useIdeStore((s) => s.setView);

  const build = () =>
    start.mutate(
      { projectId, outputType: "apk", variant: "debug" },
      {
        onSuccess: (b) => toast.success(`Build #${b.number} started. The preview opens when it finishes.`),
        onError: (e) => toast.error(isPendingBackend(e) ? "Builds aren't available yet. The build endpoint is pending." : errorMessage(e)),
      },
    );
  const showProblems = () => {
    setBottomTab("problems");
    setView("code");
  };

  const retry = (
    <Button size="sm" variant="outline" onClick={onRetry}>
      <RefreshCw /> Try again
    </Button>
  );

  let title = "Preview isn't available";
  let body: React.ReactNode = errorMessage(error);
  let action: React.ReactNode = retry;
  let icon: React.ReactNode = <AlertTriangle />;

  switch (reason) {
    case "pending":
      title = "Live preview isn't connected yet";
      body = (
        <>
          Showing your running app needs backend services that aren&apos;t deployed yet: an emulator stream and a screen renderer. Until then,
          emulator test runs capture screenshots in the{" "}
          <Link href={`/projects/${projectId}/tests`} className="text-primary hover:underline">Testing center</Link>.
        </>
      );
      action = null;
      icon = <Smartphone />;
      break;
    case "no_build":
      title = "Build your app to preview it";
      body = "The preview runs your latest build in an emulator. Nothing has been built yet.";
      action = (
        <Button size="sm" loading={start.isPending} onClick={build}>
          <Hammer /> Build and preview
        </Button>
      );
      icon = <Hammer />;
      break;
    case "build_failed":
      title = "The latest build failed";
      body = "Fix the errors, then build again to preview your app.";
      action = (
        <div className="flex flex-wrap justify-center gap-2">
          <Button size="sm" variant="outline" onClick={showProblems}>
            See problems
          </Button>
          <Button size="sm" loading={start.isPending} onClick={build}>
            <Hammer /> Build again
          </Button>
        </div>
      );
      break;
    case "build_in_progress":
      title = "Build in progress";
      body = "The preview starts automatically when the build finishes.";
      action = null;
      icon = <Loader2 className="animate-spin" />;
      break;
    case "emulator_unavailable":
      title = "No emulator is free right now";
      body = "All emulators are busy. Try again in a moment.";
      break;
    case "unsupported_project":
      title = "This project can't be previewed";
      body = errorMessage(error);
      action = null;
      break;
    default:
      title = "The preview couldn't start";
  }

  return (
    <div className="grid size-full place-items-center p-6">
      <EmptyState icon={icon} title={title} action={action}>
        {body}
      </EmptyState>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* The workspace                                                       */
/* ------------------------------------------------------------------ */

/**
 * The Preview side of the Preview | Code switch. Source priority:
 * live emulator stream, then rendered screens, then (mock mode only) a clearly
 * labelled demo, otherwise an honest explanation. It never fakes the user's app.
 */
export function PreviewWorkspace({ projectId }: { projectId: string }) {
  const emu = useEmulatorSession(projectId, true);
  const emuFailed = emu.isError;
  const screensQ = useUiScreens(projectId, { enabled: emuFailed });
  const [screenIndex, setScreenIndex] = useState(0);

  const rendered = useMemo(
    () => (screensQ.data ?? []).filter((s) => !!s.previewUrl && isSafePreviewUrl(s.previewUrl, { allowDataImage: true })),
    [screensQ.data],
  );

  // Free the emulator as soon as this session is replaced or the user leaves Preview.
  const sessionId = emu.data?.sessionId;
  useEffect(() => {
    if (!sessionId) return;
    return () => {
      api.preview.stop(projectId, sessionId).catch(() => {});
    };
  }, [projectId, sessionId]);

  const reason = emuFailed ? reasonOf(emu.error) : null;
  const session = emu.data && isSafePreviewUrl(emu.data.viewerUrl) ? emu.data : null;
  const unsafeSession = !!emu.data && !session;

  const reload = () => {
    void emu.refetch();
    if (emuFailed) void screensQ.refetch();
  };

  let tone: ChipTone = "idle";
  let label = "Preview";
  let device = "";
  let openHref: string | null = null;
  let content: React.ReactNode;

  if (session) {
    tone = "live";
    label = "Live emulator";
    device = `${session.device.name} · API ${session.device.apiLevel}`;
    openHref = session.viewerUrl;
    content = <EmulatorViewer session={session} onExpired={reload} />;
  } else if (unsafeSession) {
    label = "Unavailable";
    content = (
      <Unavailable
        projectId={projectId}
        reason="error"
        error={new Error("The preview address was rejected because it isn't a secure (https) address.")}
        onRetry={reload}
      />
    );
  } else if (emu.isPending || (emuFailed && screensQ.isPending && screensQ.fetchStatus !== "idle")) {
    label = "Starting";
    content = <Loading title={emu.isPending ? "Starting the preview…" : "Looking for rendered screens…"} />;
  } else if (emuFailed && rendered.length > 0) {
    tone = "screens";
    label = "Rendered screens";
    openHref = rendered[Math.min(screenIndex, rendered.length - 1)]!.previewUrl;
    content = <ScreensViewer screens={rendered} why={SHORT_REASON[reason ?? "error"]} index={Math.min(screenIndex, rendered.length - 1)} onSelect={setScreenIndex} />;
  } else if (IS_MOCK && reason === "pending") {
    tone = "demo";
    label = "Demo preview";
    content = <DemoPreview />;
  } else {
    label = "Unavailable";
    content = <Unavailable projectId={projectId} reason={reason ?? "error"} error={emu.error} onRetry={reload} />;
  }

  return (
    <div id="view-panel-preview" role="tabpanel" aria-labelledby="view-tab-preview" className="absolute inset-0 z-10 flex animate-fade-in flex-col bg-background">
      <div className="flex h-10 shrink-0 items-center gap-2 border-b border-border px-3">
        <SourceChip tone={tone}>{label}</SourceChip>
        {device ? <span className="hidden truncate text-[13px] text-muted-foreground sm:block">{device}</span> : null}
        <div className="ml-auto flex items-center gap-1">
          <Tooltip content="Reload preview">
            <Button variant="subtle" size="icon-sm" aria-label="Reload preview" onClick={reload} disabled={emu.isFetching && !emu.isError}>
              <RefreshCw className={cn(emu.isFetching && "animate-spin")} />
            </Button>
          </Tooltip>
          {openHref ? (
            <Tooltip content="Open in a new tab">
              <Button asChild variant="subtle" size="icon-sm">
                <a href={openHref} target="_blank" rel="noopener noreferrer" aria-label="Open preview in a new tab">
                  <ExternalLink />
                </a>
              </Button>
            </Tooltip>
          ) : null}
        </div>
      </div>
      <Stage>{content}</Stage>
    </div>
  );
}
