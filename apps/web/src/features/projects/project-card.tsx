"use client";

import Link from "next/link";
import type { AgentTask, Project } from "@apppilot/contracts";
import { CalendarDays, Package, Pin } from "lucide-react";
import { useMemo } from "react";
import { Avatar, Skeleton } from "@/components/ui/primitives";
import { useScreenshots, useTestJobs } from "@/lib/api/hooks";
import { cn, formatRelative } from "@/lib/utils";
import { isSafePreviewUrl } from "../ide/preview-workspace";
import { SOURCE_META } from "./project-meta";
import { hueOf, initialsOf, previewStateOf, type PreviewState } from "./project-preview";

/** Status colours: the dot and the text share one tone. */
const STATUS_TONE: Record<PreviewState["kind"], { dot: string; text: string }> = {
  running: { dot: "bg-primary", text: "text-primary" },
  review: { dot: "bg-primary", text: "text-primary" },
  failed: { dot: "bg-destructive", text: "text-destructive" },
  succeeded: { dot: "bg-success", text: "text-success" },
  idle: { dot: "bg-subtle-foreground/60", text: "text-subtle-foreground" },
};

/** One small status for the card: agent activity first, then the last build. */
export function CardStatus({ project, task }: { project: Project; task?: AgentTask }) {
  const state = previewStateOf(project, task);
  const label =
    state.kind === "running" || state.kind === "review" || state.kind === "failed"
      ? state.label
      : state.kind === "succeeded"
        ? "Build passed"
        : project.lastBuild?.status === "cancelled"
          ? "Build cancelled"
          : "No builds";
  // Keep the footer calm: show the verb ("Generating"); the full step is in the tooltip and for screen readers.
  const short = state.kind === "running" ? (label.split(" · ")[0] ?? label) : label;
  return (
    <span className="flex min-w-0 items-center gap-2" role={state.kind === "running" ? "status" : undefined} title={label !== short ? label : undefined}>
      <span className="relative grid size-1.5 shrink-0 place-items-center" aria-hidden>
        {state.kind === "running" ? <span className="live-ping absolute inset-0 rounded-full bg-primary" /> : null}
        <span className={cn("relative size-1.5 rounded-full", STATUS_TONE[state.kind].dot)} />
      </span>
      <span className={cn("truncate font-medium", STATUS_TONE[state.kind].text)}>
        {short}
        {label !== short ? <span className="sr-only">{label.slice(short.length)}</span> : null}
      </span>
    </span>
  );
}

/** Pin/unpin toggle. Always visible once pinned; otherwise on hover/focus (and always on touch). */
export function PinButton({ pinned, name, onToggle, className }: { pinned: boolean; name: string; onToggle: () => void; className?: string }) {
  return (
    <button
      type="button"
      onClick={(e) => {
        e.preventDefault();
        e.stopPropagation();
        onToggle();
      }}
      aria-pressed={pinned}
      aria-label={pinned ? `Unpin ${name}` : `Pin ${name} to the top`}
      title={pinned ? "Unpin" : "Pin to top"}
      className={cn(
        "grid size-7 place-items-center rounded-md outline-none transition-[opacity,background-color,color] duration-150 focus-visible:opacity-100 focus-visible:ring-2 focus-visible:ring-ring",
        pinned
          ? "bg-foreground text-background opacity-100 hover:bg-foreground/85"
          : "bg-background/80 text-muted-foreground opacity-0 backdrop-blur hover:text-foreground group-hover:opacity-100 [@media(hover:none)]:opacity-100",
        className,
      )}
    >
      {pinned ? <Pin className="size-3.5 fill-current" aria-hidden /> : <Pin className="size-3.5" aria-hidden />}
    </button>
  );
}

/* ------------------------------------------------------------------ */
/* Thumbnail                                                           */
/* ------------------------------------------------------------------ */

/** Keeps every project in the brand's violet family (indigo, violet, orchid). */
const violetHue = (id: string) => 255 + (hueOf(id) % 60);

/**
 * The newest real screenshot of the app, taken by an emulator test run. Null when the
 * project has no finished emulator run with screenshots (or the tests service is unavailable).
 */
function useProjectScreenshot(projectId: string): { url: string; caption: string } | null {
  const jobs = useTestJobs(projectId);
  const job = useMemo(
    () =>
      (jobs.data ?? [])
        .filter((j) => j.kind === "emulator" && j.state === "finished" && j.result !== "blocked")
        .sort((x, y) => (y.finishedAt ?? "").localeCompare(x.finishedAt ?? ""))[0],
    [jobs.data],
  );
  const shots = useScreenshots(job?.id ?? null);
  const shot = shots.data?.find((s) => isSafePreviewUrl(s.url, { allowDataImage: true }));
  return shot ? { url: shot.url, caption: shot.caption } : null;
}

function CardThumbnail({ project }: { project: Project }) {
  const shot = useProjectScreenshot(project.id);
  const h = violetHue(project.id);
  return (
    <div
      className="relative size-full overflow-hidden"
      style={{
        // Soft violet wash that adapts to light and dark (mixed into the card colour).
        backgroundImage: `radial-gradient(90% 120% at 15% 0%, color-mix(in oklab, oklch(0.72 0.15 ${h}) 38%, transparent), transparent 65%), radial-gradient(80% 110% at 100% 100%, color-mix(in oklab, oklch(0.7 0.14 ${(h + 35) % 360}) 30%, transparent), transparent 60%), linear-gradient(160deg, color-mix(in oklab, oklch(0.9 0.05 ${h}) 45%, var(--card)), var(--surface-2))`,
      }}
    >
      <div aria-hidden className="dot-grid absolute inset-0 opacity-25 [mask-image:radial-gradient(ellipse_70%_70%_at_50%_45%,black,transparent)]" />
      {shot ? (
        <>
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={shot.url}
            alt={`Screenshot of ${project.name}: ${shot.caption}`}
            loading="lazy"
            className="absolute bottom-0 left-1/2 h-[86%] w-auto -translate-x-1/2 translate-y-[6%] rounded-t-xl border border-white/60 shadow-[0_18px_40px_-14px_rgb(30_20_80/0.45)] transition-transform duration-300 ease-out group-hover:translate-y-[2%]"
          />
          <span className="absolute bottom-2 left-2 rounded-full bg-background/85 px-2 py-0.5 text-[10.5px] font-medium text-muted-foreground backdrop-blur">
            Test screenshot
          </span>
        </>
      ) : (
        <div aria-hidden className="absolute inset-0 grid place-items-center">
          <span
            className="relative grid size-16 place-items-center rounded-[18px] font-display text-[22px] font-semibold tracking-tight text-white shadow-[0_14px_30px_-12px_rgb(60_40_160/0.55)] ring-1 ring-white/30 transition-transform duration-300 ease-out group-hover:scale-105"
            style={{ backgroundImage: `linear-gradient(140deg, oklch(0.66 0.19 ${h}), oklch(0.5 0.21 ${(h + 30) % 360}))` }}
          >
            <span className="absolute inset-x-1.5 top-1 h-5 rounded-t-[14px] bg-white/15 blur-[1px]" />
            {project.isApkAnalysis ? <Package className="relative size-7" /> : <span className="relative">{initialsOf(project.name)}</span>}
          </span>
        </div>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Pills                                                               */
/* ------------------------------------------------------------------ */

const PILL = "inline-flex h-6 shrink-0 items-center gap-1.5 rounded-full px-2.5 text-[12px] font-medium";

const STATUS_PILL: Record<PreviewState["kind"], string> = {
  running: "bg-primary-soft text-primary",
  review: "bg-primary-soft text-primary",
  failed: "bg-destructive-soft text-destructive",
  succeeded: "bg-success-soft text-success",
  idle: "bg-surface-2 text-muted-foreground",
};

/** Build or agent status as a soft pill (Generating, Repairing, Build failed, Build passed, No builds). */
function StatusPill({ project, task }: { project: Project; task?: AgentTask }) {
  const state = previewStateOf(project, task);
  const label =
    state.kind === "running" || state.kind === "review" || state.kind === "failed"
      ? state.label
      : state.kind === "succeeded"
        ? "Build passed"
        : project.lastBuild?.status === "cancelled"
          ? "Build cancelled"
          : "No builds";
  const short = state.kind === "running" ? (label.split(" · ")[0] ?? label) : label;
  return (
    <span
      className={cn(PILL, "min-w-0", STATUS_PILL[state.kind])}
      role={state.kind === "running" ? "status" : undefined}
      title={label !== short ? label : undefined}
    >
      <span className="relative grid size-1.5 shrink-0 place-items-center" aria-hidden>
        {state.kind === "running" ? <span className="live-ping absolute inset-0 rounded-full bg-current" /> : null}
        <span className="relative size-1.5 rounded-full bg-current" />
      </span>
      <span className="truncate">
        {short}
        {label !== short ? <span className="sr-only">{label.slice(short.length)}</span> : null}
      </span>
    </span>
  );
}

/** Where the project came from: generated from a prompt, an imported Android Studio project, or an APK. */
function TypePill({ project }: { project: Project }) {
  if (project.isApkAnalysis)
    return (
      <span className={cn(PILL, "bg-warning-soft text-warning")}>
        <Package className="size-3" aria-hidden /> APK
      </span>
    );
  const source = SOURCE_META[project.source];
  return (
    <span className={cn(PILL, "border border-border bg-card text-muted-foreground")}>
      <source.icon className="size-3" aria-hidden />
      {project.source === "android_zip" ? "Imported" : source.label}
    </span>
  );
}

/* ------------------------------------------------------------------ */
/* Card                                                                */
/* ------------------------------------------------------------------ */

/**
 * The Projects page card: a preview (the latest real test screenshot, or a violet gradient with a
 * large app icon), then the name, package, type and status pills, and a date footer.
 * `actions` renders a menu top-right on the preview (shown on hover/focus, always on touch).
 */
export function ProjectCard({
  project,
  task,
  index,
  owner,
  meta,
  actions,
  pinned = false,
  onTogglePin,
}: {
  project: Project;
  task?: AgentTask;
  index: number;
  owner?: { name: string; avatarUrl?: string | null };
  /** The date line in the footer, e.g. "Created 3 days ago". */
  meta?: string;
  actions?: React.ReactNode;
  pinned?: boolean;
  onTogglePin?: () => void;
}) {
  return (
    <article
      style={{ "--i": index } as React.CSSProperties}
      title={project.description || undefined}
      className="group relative flex min-w-0 flex-col overflow-hidden rounded-2xl border border-border bg-card shadow-[0_1px_2px_rgb(21_17_43/0.04)] transition-[translate,box-shadow,border-color] duration-300 ease-out hover:-translate-y-1 hover:border-border-strong hover:shadow-[0_20px_40px_-20px_rgb(60_40_160/0.35)] focus-within:border-border-strong"
    >
      <div className="relative aspect-[16/10] border-b border-border">
        <CardThumbnail project={project} />
        {onTogglePin ? <PinButton pinned={pinned} name={project.name} onToggle={onTogglePin} className="absolute left-2.5 top-2.5 z-10" /> : null}
        {actions ? (
          <div className="absolute right-2.5 top-2.5 z-10 rounded-md bg-background/85 opacity-0 shadow-sm backdrop-blur transition-opacity duration-150 group-hover:opacity-100 focus-within:opacity-100 has-data-[state=open]:opacity-100 [@media(hover:none)]:opacity-100">
            {actions}
          </div>
        ) : null}
      </div>

      <div className="flex flex-1 flex-col px-4 pb-3.5 pt-3.5">
        <Link
          href={`/projects/${project.id}/ide`}
          className="block min-w-0 rounded-sm outline-none after:absolute after:inset-0 after:rounded-2xl focus-visible:after:ring-2 focus-visible:after:ring-ring"
        >
          <h3 className="truncate text-[15px] font-semibold leading-snug tracking-tight">{project.name}</h3>
        </Link>
        <p className={cn("mt-0.5 truncate font-mono text-[12px] leading-5", project.packageName ? "text-subtle-foreground" : "text-subtle-foreground/70")}>
          {project.packageName ?? "No package name yet"}
        </p>

        <div className="mt-3 flex min-w-0 items-center gap-1.5 overflow-hidden">
          <TypePill project={project} />
          <StatusPill project={project} task={task} />
        </div>

        <div className="mt-3.5 flex min-w-0 items-center justify-between gap-2 border-t border-border pt-3 text-[12.5px] text-subtle-foreground">
          <span className="inline-flex min-w-0 items-center gap-1.5">
            <CalendarDays className="size-3.5 shrink-0" aria-hidden />
            <span className="truncate">{meta ?? `Created ${formatRelative(project.createdAt)}`}</span>
          </span>
          {owner ? (
            <span className="inline-flex shrink-0 items-center" title={owner.name}>
              <Avatar name={owner.name} src={owner.avatarUrl} className="size-6 ring-0 [&_span]:text-[10px]" />
              <span className="sr-only">Owner {owner.name}</span>
            </span>
          ) : null}
        </div>
      </div>
    </article>
  );
}

/** Loading placeholder with the card's shape. */
export function ProjectCardSkeleton({ style }: { style?: React.CSSProperties }) {
  return (
    <div style={style} aria-hidden className="overflow-hidden rounded-2xl border border-border bg-card">
      <Skeleton className="aspect-[16/10] rounded-none" />
      <div className="grid gap-2 p-4">
        <Skeleton className="h-4 w-2/3" />
        <Skeleton className="h-3 w-1/2" />
        <div className="mt-1 flex gap-1.5">
          <Skeleton className="h-6 w-20 rounded-full" />
          <Skeleton className="h-6 w-24 rounded-full" />
        </div>
        <Skeleton className="mt-2 h-3 w-1/3" />
      </div>
    </div>
  );
}
