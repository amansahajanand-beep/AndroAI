"use client";

import Link from "next/link";
import type { AgentTask, Project } from "@apppilot/contracts";
import { FileArchive, Package, Plus, Sparkle, type LucideIcon } from "lucide-react";
import { cn, formatRelative } from "@/lib/utils";
import { initialsOf, previewStateOf, type PreviewState } from "./project-preview";

/** Status colours: the dot and the text share one tone. */
const STATUS_TONE: Record<PreviewState["kind"], { dot: string; text: string }> = {
  running: { dot: "bg-primary", text: "text-primary" },
  review: { dot: "bg-primary", text: "text-primary" },
  failed: { dot: "bg-destructive", text: "text-destructive" },
  succeeded: { dot: "bg-success", text: "text-success" },
  idle: { dot: "bg-subtle-foreground/60", text: "text-subtle-foreground" },
};

/** Two-letter monogram: initials for multi-word names, first two letters otherwise ("Trailhead" → "TH"). */
function monogramOf(name: string) {
  const words = name.trim().split(/s+/).filter(Boolean);
  if (words.length > 1) return initialsOf(name);
  const w = words[0] ?? "";
  return (w.slice(0, 1) + (w.slice(1).match(/[A-Z]/)?.[0] ?? w.slice(1, 2))).toUpperCase();
}

/** Short source labels with their icon, as shown in the card meta row. */
const SOURCE: Record<Project["source"], { label: string; icon: LucideIcon }> = {
  prompt: { label: "From prompt", icon: Sparkle },
  android_zip: { label: "Imported", icon: FileArchive },
  apk: { label: "APK analysis", icon: Package },
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

/**
 * The project card shared by the Projects page and the dashboard: violet icon tile, name and
 * package, one-line description, source + tech chips, then a divider and a coloured status.
 * `actions` renders a menu top-right (hidden until hover/focus, always shown on touch).
 */
export function ProjectCard({ project, task, index, actions }: { project: Project; task?: AgentTask; index: number; actions?: React.ReactNode }) {
  const source = SOURCE[project.source];
  const apk = project.isApkAnalysis;
  return (
    <article
      style={{ "--i": index } as React.CSSProperties}
      className="group relative flex min-w-0 flex-col rounded-[12px] border border-border bg-card transition-[border-color,background-color,box-shadow] duration-150 hover:border-border-strong hover:shadow-[0_1px_2px_rgb(21_17_43/0.06)] dark:hover:bg-surface-2"
    >
      <div className="flex flex-1 flex-col px-5 pt-4">
        <div className={cn("flex items-center gap-3", actions ? "pr-8" : undefined)}>
          <span
            aria-hidden
            className={cn(
              "grid size-8 shrink-0 place-items-center rounded-sm text-[12px] font-semibold tracking-wide",
              apk ? "bg-warning-soft text-warning" : "bg-primary-soft text-primary",
            )}
          >
            {apk ? <Package className="size-4" /> : monogramOf(project.name)}
          </span>
          <Link href={`/projects/${project.id}/ide`} className="min-w-0 rounded-sm outline-none after:absolute after:inset-0 after:z-0 after:rounded-[12px] focus-visible:after:ring-2 focus-visible:after:ring-ring">
            <h3 className="truncate text-[15px] font-semibold leading-tight">{project.name}</h3>
            {project.packageName ? <p className="truncate font-mono text-[12px] leading-snug text-subtle-foreground">{project.packageName}</p> : null}
          </Link>
        </div>
        {actions ? (
          <div className="absolute right-3 top-3 z-10 opacity-0 transition-opacity duration-150 group-hover:opacity-100 focus-within:opacity-100 has-data-[state=open]:opacity-100 [@media(hover:none)]:opacity-100">
            {actions}
          </div>
        ) : null}

        <p className="mt-2.5 truncate text-[13.5px] leading-normal text-muted-foreground" title={project.description || undefined}>
          {project.description}
        </p>

        <div className="mt-auto flex min-w-0 flex-wrap items-center gap-x-1.5 gap-y-1.5 pb-3.5 pt-5">
          <span className={cn("inline-flex shrink-0 items-center gap-1.5 text-[12.5px]", apk ? "font-medium text-warning" : "text-subtle-foreground")}>
            <source.icon className={cn("size-3.5", apk ? "text-warning" : "text-primary")} aria-hidden />
            {source.label}
          </span>
          <span aria-hidden className="mx-1 size-[3px] shrink-0 rounded-full bg-border-strong" />
          {[project.language === "kotlin" ? "Kotlin" : "Java", project.uiToolkit === "compose" ? "Compose" : "XML views"].map((t) => (
            <span key={t} className="shrink-0 rounded-[5px] border border-border bg-surface-2 px-1.5 py-px text-[12px] font-medium text-foreground/80">
              {t}
            </span>
          ))}
        </div>
      </div>

      <div className="flex items-center justify-between gap-3 border-t border-border px-5 py-3 text-[12.5px]">
        <CardStatus project={project} task={task} />
        <span className="shrink-0 text-subtle-foreground">Updated {formatRelative(project.updatedAt)}</span>
      </div>
    </article>
  );
}

export function NewProjectCard({ index }: { index: number }) {
  return (
    <Link
      href="/projects/new"
      style={{ "--i": index } as React.CSSProperties}
      className="group flex min-h-44 flex-col items-center justify-center gap-1.5 rounded-[12px] border border-dashed border-border-strong p-5 text-center transition-colors duration-150 hover:border-primary/50 hover:bg-primary-soft/40"
    >
      <span className="mb-1 grid size-8 place-items-center rounded-sm bg-primary-soft text-primary">
        <Plus className="size-4" aria-hidden />
      </span>
      <span className="text-[14px] font-semibold text-foreground">New project</span>
      <span className="text-[12.5px] text-subtle-foreground">Start from a prompt, a ZIP or an APK.</span>
    </Link>
  );
}

/** Loading placeholder matching the card size. */
export const PROJECT_CARD_SKELETON = "h-44 rounded-[12px]";
