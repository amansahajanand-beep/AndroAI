"use client";

import Link from "next/link";
import type { AgentTask, Project } from "@apppilot/contracts";
import { AlertTriangle, ChevronRight, Folder, Package } from "lucide-react";
import { Avatar, Skeleton } from "@/components/ui/primitives";
import { cn, formatRelative } from "@/lib/utils";
import type { ProjectFolder } from "@/stores/project-folders";
import { CardStatus, PinButton } from "./project-card";
import { ProjectThumb } from "./project-preview";

/*
 * Columns (md and up): name | status | created | owner | actions.
 * Below md the row collapses to icon + name/package, with status and date on one line under it.
 */
const COLS = "md:grid md:grid-cols-[minmax(0,1fr)_minmax(8rem,11rem)_minmax(6.5rem,8.5rem)_minmax(7rem,10rem)_4.5rem] md:items-center md:gap-4";
const ROW =
  "group relative flex items-center gap-3 border-b border-border px-4 py-3 transition-colors duration-150 last:border-b-0 hover:bg-surface-2/70 focus-within:bg-surface-2/70 md:px-5";
/** Hover/focus reveal for row controls; always visible on touch screens. */
const REVEAL = "opacity-0 transition-opacity duration-150 group-hover:opacity-100 focus-within:opacity-100 has-data-[state=open]:opacity-100 [@media(hover:none)]:opacity-100";

type Owner = { name: string; avatarUrl?: string | null };

function OwnerCell({ owner }: { owner?: Owner }) {
  if (!owner) return <span className="text-subtle-foreground">—</span>;
  return (
    <span className="flex min-w-0 items-center gap-2 text-[13px] text-muted-foreground">
      <Avatar name={owner.name} src={owner.avatarUrl} className="size-6 shrink-0 ring-0 [&_span]:text-[10px]" />
      <span className="truncate">{owner.name}</span>
    </span>
  );
}

function ProjectRow({
  project,
  task,
  owner,
  pinned,
  onTogglePin,
  menu,
}: {
  project: Project;
  task?: AgentTask;
  owner?: Owner;
  pinned: boolean;
  onTogglePin: () => void;
  menu: React.ReactNode;
}) {
  const created = formatRelative(project.createdAt);
  return (
    <li className={cn(ROW, COLS)} title={project.description || undefined}>
      {/* Name: the whole row is this link (stretched), so any click opens the IDE. */}
      <div className="flex min-w-0 flex-1 items-center gap-3">
        <ProjectThumb project={project} className="size-9 rounded-[10px] text-[12px]" />
        <div className="min-w-0">
          <Link
            href={`/projects/${project.id}/ide`}
            className="flex min-w-0 items-center gap-2 rounded-sm outline-none after:absolute after:inset-0 focus-visible:after:ring-2 focus-visible:after:ring-inset focus-visible:after:ring-ring"
          >
            <span className="truncate text-[14px] font-semibold text-foreground">{project.name}</span>
            {project.isApkAnalysis ? (
              <span className="inline-flex shrink-0 items-center gap-1 rounded-md bg-warning-soft px-1.5 py-px text-[11px] font-medium text-warning">
                <Package className="size-3" aria-hidden /> APK
              </span>
            ) : null}
          </Link>
          <p className="truncate font-mono text-[12px] leading-5 text-subtle-foreground">{project.packageName ?? "No package name yet"}</p>
          {/* Mobile: status and date under the name. */}
          <div className="mt-1 flex min-w-0 items-center gap-2 text-[12.5px] md:hidden">
            <CardStatus project={project} task={task} />
            <span className="text-subtle-foreground" aria-hidden>
              ·
            </span>
            <span className="shrink-0 text-subtle-foreground">{created}</span>
          </div>
        </div>
      </div>

      <div className="hidden min-w-0 text-[13px] md:block">
        <CardStatus project={project} task={task} />
      </div>
      <div className="hidden text-[13px] text-muted-foreground md:block">
        <time dateTime={project.createdAt}>{created}</time>
      </div>
      <div className="hidden min-w-0 md:block">
        <OwnerCell owner={owner} />
      </div>

      {/* Actions sit above the stretched link. */}
      <div className="relative z-10 flex shrink-0 items-center justify-end gap-1">
        <PinButton pinned={pinned} name={project.name} onToggle={onTogglePin} />
        <div className={REVEAL}>{menu}</div>
      </div>
    </li>
  );
}

function FolderRow({ folder, count, onOpen, menu }: { folder: ProjectFolder; count: number; onOpen: () => void; menu: React.ReactNode }) {
  return (
    <li className={cn(ROW, COLS)}>
      <div className="flex min-w-0 flex-1 items-center gap-3">
        <span className="grid size-9 shrink-0 place-items-center rounded-[10px] bg-surface-3 text-muted-foreground transition-colors group-hover:text-foreground" aria-hidden>
          <Folder className="size-4.5" />
        </span>
        <button
          type="button"
          onClick={onOpen}
          className="min-w-0 rounded-sm text-left outline-none after:absolute after:inset-0 focus-visible:after:ring-2 focus-visible:after:ring-inset focus-visible:after:ring-ring"
        >
          <span className="block truncate text-[14px] font-semibold">{folder.name}</span>
          <span className="block text-[12.5px] text-subtle-foreground">
            {count} {count === 1 ? "project" : "projects"}
          </span>
        </button>
      </div>
      <div className="hidden md:block" />
      <div className="hidden text-[13px] text-muted-foreground md:block">
        <time dateTime={folder.createdAt}>{formatRelative(folder.createdAt)}</time>
      </div>
      <div className="hidden md:block" />
      <div className="relative z-10 flex shrink-0 items-center justify-end gap-1">
        <ChevronRight className="size-4 text-subtle-foreground md:hidden" aria-hidden />
        <div className={REVEAL}>{menu}</div>
      </div>
    </li>
  );
}

/** Table-style project list: folders first (when given), then projects. */
export function ProjectList({
  projects,
  folders = [],
  countIn,
  onOpenFolder,
  folderMenuFor,
  taskByProject,
  owner,
  pinned,
  onTogglePin,
  menuFor,
}: {
  projects: Project[];
  folders?: ProjectFolder[];
  countIn: (f: ProjectFolder) => number;
  onOpenFolder: (id: string) => void;
  folderMenuFor: (f: ProjectFolder) => React.ReactNode;
  taskByProject: Map<string, AgentTask>;
  owner?: Owner;
  pinned: string[];
  onTogglePin: (id: string) => void;
  menuFor: (p: Project) => React.ReactNode;
}) {
  return (
    <div className="overflow-hidden rounded-xl border border-border bg-card shadow-[0_1px_2px_rgb(21_17_43/0.04)]">
      <div
        className={cn(
          "hidden border-b border-border bg-surface-2/60 px-5 py-2.5 text-[11.5px] font-semibold uppercase tracking-[0.06em] text-subtle-foreground md:grid",
          COLS,
        )}
        aria-hidden
      >
        <span>Name</span>
        <span>Status</span>
        <span>Created</span>
        <span>Owner</span>
        <span />
      </div>
      <ul aria-label="Projects">
        {folders.map((f) => (
          <FolderRow key={f.id} folder={f} count={countIn(f)} onOpen={() => onOpenFolder(f.id)} menu={folderMenuFor(f)} />
        ))}
        {projects.map((p) => (
          <ProjectRow
            key={p.id}
            project={p}
            task={taskByProject.get(p.id)}
            owner={owner}
            pinned={pinned.includes(p.id)}
            onTogglePin={() => onTogglePin(p.id)}
            menu={menuFor(p)}
          />
        ))}
      </ul>
    </div>
  );
}

/** A quiet notice above the list when any project's latest build failed. Links to that project's builds. */
export function NeedsAttention({ projects }: { projects: Project[] }) {
  const failed = projects.filter((p) => p.lastBuild?.status === "failed");
  if (failed.length === 0) return null;
  return (
    <section
      aria-label="Needs attention"
      className="mb-4 flex flex-wrap items-center gap-x-3 gap-y-2 rounded-xl border border-destructive/20 bg-destructive-soft/60 px-4 py-2.5"
    >
      <span className="inline-flex items-center gap-2 text-[13px] font-semibold text-destructive">
        <AlertTriangle className="size-4" aria-hidden />
        Needs attention
      </span>
      <span className="text-[13px] text-muted-foreground">
        {failed.length === 1 ? "1 project's latest build failed" : `${failed.length} projects' latest builds failed`}
      </span>
      <span className="flex flex-wrap gap-1.5">
        {failed.map((p) => (
          <Link
            key={p.id}
            href={`/projects/${p.id}/builds`}
            className="inline-flex h-7 items-center gap-1.5 rounded-full border border-border bg-card px-2.5 text-[12.5px] font-medium text-foreground outline-none transition-colors hover:border-destructive/40 hover:text-destructive focus-visible:ring-2 focus-visible:ring-ring"
          >
            <span className="size-1.5 rounded-full bg-destructive" aria-hidden />
            {p.name}
            <ChevronRight className="size-3.5 text-subtle-foreground" aria-hidden />
          </Link>
        ))}
      </span>
    </section>
  );
}

/** Loading placeholder with the list's shape. */
export function ProjectListSkeleton({ rows = 6 }: { rows?: number }) {
  return (
    <div className="overflow-hidden rounded-xl border border-border bg-card" aria-busy="true" aria-label="Loading projects">
      <div className="hidden h-10 border-b border-border bg-surface-2/60 md:block" />
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className={cn("flex items-center gap-3 border-b border-border px-4 py-3 last:border-b-0 md:px-5", COLS)} style={{ opacity: 1 - i * 0.12 }}>
          <div className="flex flex-1 items-center gap-3">
            <Skeleton className="size-9 rounded-[10px]" />
            <div className="grid flex-1 gap-1.5">
              <Skeleton className="h-3.5 w-40 max-w-full" />
              <Skeleton className="h-3 w-28 max-w-full" />
            </div>
          </div>
          <Skeleton className="hidden h-3 w-24 md:block" />
          <Skeleton className="hidden h-3 w-20 md:block" />
          <Skeleton className="hidden h-3 w-24 md:block" />
          <span className="hidden md:block" />
        </div>
      ))}
    </div>
  );
}
