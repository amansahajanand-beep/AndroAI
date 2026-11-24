"use client";

import Link from "next/link";
import type { AgentTask, Project } from "@apppilot/contracts";
import { Pin } from "lucide-react";
import { Avatar, Skeleton } from "@/components/ui/primitives";
import { cn, formatRelative } from "@/lib/utils";
import { SOURCE_META } from "./project-meta";
import { ProjectPreview, previewStateOf, type PreviewState } from "./project-preview";

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

/**
 * The Projects page card (Lovable-style): a large generated preview with the live status on it,
 * then the owner's avatar, the project name and a date line. The description is the tooltip.
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
  /** The date line under the name, e.g. "Created 3 days ago". */
  meta?: string;
  actions?: React.ReactNode;
  pinned?: boolean;
  onTogglePin?: () => void;
}) {
  const state = previewStateOf(project, task);
  const source = SOURCE_META[project.source];
  return (
    <article style={{ "--i": index } as React.CSSProperties} title={project.description || undefined} className="group relative min-w-0">
      <div className="relative aspect-[16/10] overflow-hidden rounded-xl border border-border transition-[border-color,box-shadow] duration-300 group-hover:border-border-strong group-hover:shadow-[0_12px_32px_-16px_rgb(0_0_0/0.35)] group-focus-within:border-border-strong">
        <ProjectPreview project={project} className="h-full" />
        {onTogglePin ? <PinButton pinned={pinned} name={project.name} onToggle={onTogglePin} className="absolute left-2 top-2 z-10" /> : null}
        {actions ? (
          <div className="absolute right-2 top-2 z-10 rounded-md bg-background/80 opacity-0 backdrop-blur transition-opacity duration-150 group-hover:opacity-100 focus-within:opacity-100 has-data-[state=open]:opacity-100 [@media(hover:none)]:opacity-100">
            {actions}
          </div>
        ) : null}
      </div>

      <div className="mt-3 flex min-w-0 items-start gap-2.5 px-0.5">
        {owner ? <Avatar name={owner.name} src={owner.avatarUrl} className="mt-0.5 size-7 ring-0 [&_span]:text-[11px]" /> : null}
        <div className="min-w-0 flex-1">
          <Link
            href={`/projects/${project.id}/ide`}
            className="block min-w-0 rounded-sm outline-none after:absolute after:inset-0 after:rounded-xl focus-visible:after:ring-2 focus-visible:after:ring-ring"
          >
            <h3 className="truncate text-[14.5px] font-semibold leading-snug">{project.name}</h3>
          </Link>
          <div className="mt-0.5 flex min-w-0 items-center gap-1.5 text-[12.5px] text-subtle-foreground">
            {state.kind !== "idle" ? (
              <>
                <CardStatus project={project} task={task} />
                <span aria-hidden>·</span>
              </>
            ) : null}
            {project.isApkAnalysis ? (
              <>
                <span className="inline-flex shrink-0 items-center gap-1 font-medium text-warning">
                  <source.icon className="size-3" aria-hidden /> APK
                </span>
                <span aria-hidden>·</span>
              </>
            ) : null}
            <span className="truncate">{meta ?? `Edited ${formatRelative(project.updatedAt)}`}</span>
            {owner ? <span className="sr-only">, owner {owner.name}</span> : null}
          </div>
        </div>
      </div>
    </article>
  );
}

/** Loading placeholder with the card's shape. */
export function ProjectCardSkeleton({ style }: { style?: React.CSSProperties }) {
  return (
    <div style={style} aria-hidden>
      <Skeleton className="aspect-[16/10] rounded-xl" />
      <div className="mt-3 flex gap-2.5">
        <Skeleton className="size-7 rounded-full" />
        <div className="grid flex-1 gap-1.5 pt-0.5">
          <Skeleton className="h-3.5 w-2/3" />
          <Skeleton className="h-3 w-1/3" />
        </div>
      </div>
    </div>
  );
}
