"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import type { AgentTask, Project } from "@apppilot/contracts";
import {
  ArrowDownUp,
  ChevronRight,
  Folder,
  FolderMinus,
  FolderOpen,
  FolderPlus,
  LayoutGrid,
  List,
  ListFilter,
  MoreHorizontal,
  Pencil,
  Plus,
  Search,
  SearchX,
  Sparkles,
  Trash2,
  X,
} from "lucide-react";
import { PageBody } from "@/components/layout/page";
import { ErrorState } from "@/components/states/states";
import { BuildStatusBadge } from "@/components/status/status-badge";
import { Button } from "@/components/ui/button";
import {
  ConfirmDialog,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/overlays";
import { Avatar, Badge, Card, Input, Table, TBody, TD, TH, THead, TR } from "@/components/ui/primitives";
import { useAgentTasks, useProjects, useSession } from "@/lib/api/hooks";
import { formatRelative } from "@/lib/utils";
import { useProjectFolders, type ProjectFolder } from "@/stores/project-folders";
import { pinnedFirst, useProjectPins } from "@/stores/project-pins";
import { useUiStore } from "@/stores/ui-store";
import { CardStatus, PinButton, ProjectCard, ProjectCardSkeleton } from "./project-card";
import { ProjectThumb } from "./project-preview";

/* ------------------------------------------------------------------ */
/* Sorting and filters                                                  */
/* ------------------------------------------------------------------ */

type Sort = "created" | "updated" | "name";
const SORTS: { value: Sort; label: string }[] = [
  { value: "created", label: "Date created" },
  { value: "updated", label: "Last edited" },
  { value: "name", label: "Name (A–Z)" },
];

const SORTERS: Record<Sort, (a: Project, b: Project) => number> = {
  created: (a, b) => b.createdAt.localeCompare(a.createdAt),
  updated: (a, b) => b.updatedAt.localeCompare(a.updatedAt),
  name: (a, b) => a.name.localeCompare(b.name, undefined, { sensitivity: "base" }),
};

interface FilterGroup {
  key: string;
  label: string;
  options: { value: string; label: string }[];
  test: (p: Project, value: string) => boolean;
}

/** Options in a group are OR-ed; groups are AND-ed together. */
const FILTER_GROUPS: FilterGroup[] = [
  {
    key: "source",
    label: "Source",
    options: [
      { value: "prompt", label: "From prompt" },
      { value: "android_zip", label: "Imported project" },
      { value: "apk", label: "APK analysis" },
    ],
    test: (p, v) => p.source === v,
  },
  {
    key: "status",
    label: "Status",
    options: [
      { value: "running", label: "Agent running" },
      { value: "passed", label: "Build passed" },
      { value: "failed", label: "Build failed" },
      { value: "none", label: "No builds" },
    ],
    test: (p, v) =>
      v === "running"
        ? p.activeTaskCount > 0
        : v === "passed"
          ? p.lastBuild?.status === "succeeded"
          : v === "failed"
            ? p.lastBuild?.status === "failed"
            : !p.lastBuild,
  },
  {
    key: "language",
    label: "Language",
    options: [
      { value: "kotlin", label: "Kotlin" },
      { value: "java", label: "Java" },
    ],
    test: (p, v) => p.language === v,
  },
  {
    key: "ui",
    label: "UI toolkit",
    options: [
      { value: "compose", label: "Jetpack Compose" },
      { value: "xml", label: "XML views" },
    ],
    test: (p, v) => p.uiToolkit === v,
  },
];

const filterKey = (group: string, value: string) => `${group}:${value}`;

function matchesFilters(p: Project, active: Set<string>) {
  return FILTER_GROUPS.every((g) => {
    const chosen = g.options.filter((o) => active.has(filterKey(g.key, o.value)));
    return chosen.length === 0 || chosen.some((o) => g.test(p, o.value));
  });
}

/* ------------------------------------------------------------------ */
/* Small pieces                                                          */
/* ------------------------------------------------------------------ */

const TOOL_BTN =
  "inline-flex h-9 items-center gap-2 rounded-lg border border-border-strong px-3 text-[13.5px] font-medium text-foreground/90 outline-none transition-colors hover:bg-surface-2 focus-visible:ring-2 focus-visible:ring-ring data-[state=open]:bg-surface-2";

/** First-run empty state: one calm message and one clear next step. */
function FirstProjectEmpty() {
  return (
    <div className="flex flex-col items-center rounded-xl border border-dashed border-border-strong px-6 py-16 text-center sm:py-24">
      <span className="grid size-12 place-items-center rounded-xl border border-border bg-surface-2 text-muted-foreground" aria-hidden>
        <Sparkles className="size-5" />
      </span>
      <h2 className="mt-5 text-balance text-[22px] font-semibold tracking-[-0.02em]">Your first app is one sentence away</h2>
      <p className="mx-auto mt-2 max-w-md text-pretty text-[15px] leading-relaxed text-muted-foreground">
        Describe an app, upload an Android Studio project, or inspect an APK. Everything you create shows up here.
      </p>
      <Button asChild size="lg" className="mt-7">
        <Link href="/projects/new">
          <Plus /> New project
        </Link>
      </Button>
    </div>
  );
}

/** Create or rename a folder. */
function FolderNameDialog({
  open,
  onOpenChange,
  title,
  submitLabel,
  initial = "",
  onSubmit,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  submitLabel: string;
  initial?: string;
  onSubmit: (name: string) => void;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        {/* Keyed so the field resets every time the dialog opens. */}
        <FolderNameForm key={open ? initial : "closed"} title={title} submitLabel={submitLabel} initial={initial} onCancel={() => onOpenChange(false)} onSubmit={onSubmit} />
      </DialogContent>
    </Dialog>
  );
}

function FolderNameForm({
  title,
  submitLabel,
  initial,
  onCancel,
  onSubmit,
}: {
  title: string;
  submitLabel: string;
  initial: string;
  onCancel: () => void;
  onSubmit: (name: string) => void;
}) {
  const [name, setName] = useState(initial);
  return (
    <form
      className="grid gap-4"
      onSubmit={(e) => {
        e.preventDefault();
        if (name.trim()) onSubmit(name.trim());
      }}
    >
      <DialogHeader>
        <DialogTitle>{title}</DialogTitle>
        <DialogDescription>Folders are saved in this browser.</DialogDescription>
      </DialogHeader>
      <label className="grid gap-1.5 text-[14px]">
        <span className="font-medium">Name</span>
        <Input value={name} onChange={(e) => setName(e.target.value)} maxLength={60} placeholder="e.g. Client apps" autoFocus />
      </label>
      <DialogFooter>
        <Button type="button" variant="outline" onClick={onCancel}>
          Cancel
        </Button>
        <Button type="submit" disabled={!name.trim()}>
          {submitLabel}
        </Button>
      </DialogFooter>
    </form>
  );
}

/** Per-project menu: only folder actions (opening, builds and settings live on the project itself). */
function ProjectFolderMenu({
  project,
  folders,
  folderId,
  onMove,
  onNewFolder,
}: {
  project: Project;
  folders: ProjectFolder[];
  folderId: string | null;
  onMove: (folderId: string | null) => void;
  onNewFolder: () => void;
}) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="subtle" size="icon-sm" aria-label={`Folder options for ${project.name}`}>
          <MoreHorizontal />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-56">
        <DropdownMenuLabel>Move to folder</DropdownMenuLabel>
        {folders.length > 0 ? (
          <DropdownMenuRadioGroup value={folderId ?? ""} onValueChange={(v) => onMove(v || null)}>
            {folders.map((f) => (
              <DropdownMenuRadioItem key={f.id} value={f.id}>
                <Folder /> <span className="truncate">{f.name}</span>
              </DropdownMenuRadioItem>
            ))}
          </DropdownMenuRadioGroup>
        ) : null}
        <DropdownMenuItem onSelect={onNewFolder}>
          <FolderPlus /> New folder…
        </DropdownMenuItem>
        {folderId ? (
          <>
            <DropdownMenuSeparator />
            <DropdownMenuItem onSelect={() => onMove(null)}>
              <FolderMinus /> Remove from folder
            </DropdownMenuItem>
          </>
        ) : null}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function FolderMenu({ folder, onRename, onDelete }: { folder: ProjectFolder; onRename: () => void; onDelete: () => void }) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="subtle" size="icon-sm" aria-label={`Options for folder ${folder.name}`}>
          <MoreHorizontal />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        <DropdownMenuItem onSelect={onRename}>
          <Pencil /> Rename
        </DropdownMenuItem>
        <DropdownMenuItem variant="destructive" onSelect={onDelete}>
          <Trash2 /> Delete folder
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

/* ------------------------------------------------------------------ */
/* Page                                                                  */
/* ------------------------------------------------------------------ */

export function ProjectsScreen() {
  const projects = useProjects();
  const { data: session } = useSession();
  const view = useUiStore((s) => s.projectsView);
  const setView = useUiStore((s) => s.setProjectsView);
  const { folders, placement, create, rename, remove, move } = useProjectFolders();
  const { pinned, toggle: togglePin } = useProjectPins();

  const [q, setQ] = useState("");
  const [sort, setSort] = useState<Sort>("created");
  const [filters, setFilters] = useState<Set<string>>(() => new Set());
  const [openFolderId, setOpenFolderId] = useState<string | null>(null);
  // Folder dialogs: create (optionally moving a project into the new folder), rename, delete.
  const [creating, setCreating] = useState<{ moveProjectId?: string } | null>(null);
  const [renaming, setRenaming] = useState<ProjectFolder | null>(null);
  const [deleting, setDeleting] = useState<ProjectFolder | null>(null);

  const all = useMemo(() => projects.data?.items ?? [], [projects.data]);
  const folderIds = new Set(folders.map((f) => f.id));
  const folderOf = (p: Project): string | null => {
    const id = placement[p.id];
    return id && folderIds.has(id) ? id : null;
  };
  const openFolder = folders.find((f) => f.id === openFolderId) ?? null;

  const needle = q.trim().toLowerCase();
  const narrowing = needle !== "" || filters.size > 0;

  // Inside a folder: its projects. At the top level: projects not in a folder,
  // or every project while searching/filtering so nothing hides inside a folder.
  const scope = all.filter((p) => (openFolder ? folderOf(p) === openFolder.id : narrowing || !folderOf(p)));
  // Pinned projects stay on top; the chosen sort orders everything below (and among the pinned ones by pin time).
  const visible = pinnedFirst(
    scope
      .filter((p) => !needle || p.name.toLowerCase().includes(needle) || (p.packageName ?? "").toLowerCase().includes(needle))
      .filter((p) => matchesFilters(p, filters))
      .sort(SORTERS[sort]),
    pinned,
  );
  const showFolders = !openFolder && !narrowing && folders.length > 0;
  const countIn = (f: ProjectFolder) => all.filter((p) => folderOf(p) === f.id).length;

  // The live step on each card comes from active agent tasks (only fetched when something runs).
  const running = all.reduce((n, p) => n + p.activeTaskCount, 0);
  const activeTasks = useAgentTasks({ status: "active" }, { enabled: running > 0 });
  const taskByProject = useMemo(() => {
    const m = new Map<string, AgentTask>();
    for (const t of activeTasks.data ?? []) if (!m.has(t.projectId)) m.set(t.projectId, t);
    return m;
  }, [activeTasks.data]);

  const owner = session?.user ? { name: session.user.name, avatarUrl: session.user.avatarUrl } : undefined;
  const metaFor = (p: Project) => (sort === "updated" ? `Edited ${formatRelative(p.updatedAt)}` : `Created ${formatRelative(p.createdAt)}`);

  const toggleFilter = (key: string) =>
    setFilters((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  const clearAll = () => {
    setQ("");
    setFilters(new Set());
  };
  const activeChips = FILTER_GROUPS.flatMap((g) => g.options.filter((o) => filters.has(filterKey(g.key, o.value))).map((o) => ({ key: filterKey(g.key, o.value), label: o.label })));

  const menuFor = (p: Project) => (
    <ProjectFolderMenu
      project={p}
      folders={folders}
      folderId={folderOf(p)}
      onMove={(id) => move(p.id, id)}
      onNewFolder={() => setCreating({ moveProjectId: p.id })}
    />
  );

  const hasProjects = all.length > 0;

  return (
    <PageBody className="max-w-[1400px]">
      {/* Title row */}
      <header className="flex flex-wrap items-center justify-between gap-3 pb-6">
        {openFolder ? (
          <nav aria-label="Breadcrumb" className="flex min-w-0 items-center gap-1.5 text-[24px] font-semibold tracking-[-0.03em]">
            <button type="button" onClick={() => setOpenFolderId(null)} className="rounded-md text-muted-foreground outline-none transition-colors hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring">
              Projects
            </button>
            <ChevronRight className="size-5 shrink-0 text-subtle-foreground" aria-hidden />
            <h1 className="truncate" aria-current="page">
              {openFolder.name}
            </h1>
            <FolderMenu folder={openFolder} onRename={() => setRenaming(openFolder)} onDelete={() => setDeleting(openFolder)} />
          </nav>
        ) : (
          <h1 className="text-[24px] font-semibold tracking-[-0.03em]">Projects</h1>
        )}
        <div className="flex items-center gap-2">
          <Button variant="outline" onClick={() => setCreating({})}>
            <FolderPlus /> New folder
          </Button>
          <Button asChild>
            <Link href="/projects/new">
              <Plus /> New project
            </Link>
          </Button>
        </div>
      </header>

      {/* Toolbar: search, filter, view */}
      {hasProjects || projects.isPending ? (
        <div className="mb-6 grid gap-3">
          <div className="flex flex-wrap items-center gap-2">
            <div className="relative min-w-52 flex-1 sm:max-w-sm">
              <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-subtle-foreground" aria-hidden />
              <Input
                value={q}
                onChange={(e) => setQ(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Escape") setQ("");
                }}
                placeholder="Search by name or package"
                className="h-9 rounded-lg pl-9 pr-8"
                aria-label="Search projects"
              />
              {q ? (
                <button
                  type="button"
                  onClick={() => setQ("")}
                  aria-label="Clear search"
                  className="absolute right-1.5 top-1/2 grid size-6 -translate-y-1/2 place-items-center rounded-md text-muted-foreground transition-colors hover:bg-surface-3 hover:text-foreground"
                >
                  <X className="size-3.5" />
                </button>
              ) : null}
            </div>

            <div className="ml-auto flex items-center gap-2">
              <DropdownMenu>
                <DropdownMenuTrigger className={TOOL_BTN}>
                  <ListFilter className="size-4" aria-hidden />
                  Filter
                  {filters.size > 0 ? (
                    <span className="grid h-5 min-w-5 place-items-center rounded-full bg-foreground px-1.5 text-[11px] font-semibold text-background">{filters.size}</span>
                  ) : null}
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end" className="max-h-[70vh] w-60 overflow-y-auto">
                  {FILTER_GROUPS.map((g, i) => (
                    <div key={g.key} role="group" aria-label={g.label}>
                      {i > 0 ? <DropdownMenuSeparator /> : null}
                      <DropdownMenuLabel>{g.label}</DropdownMenuLabel>
                      {g.options.map((o) => {
                        const key = filterKey(g.key, o.value);
                        const count = all.filter((p) => g.test(p, o.value)).length;
                        return (
                          <DropdownMenuCheckboxItem key={key} checked={filters.has(key)} onCheckedChange={() => toggleFilter(key)} onSelect={(e) => e.preventDefault()}>
                            <span className="flex-1">{o.label}</span>
                            <span className="text-[12px] tabular-nums text-subtle-foreground">{count}</span>
                          </DropdownMenuCheckboxItem>
                        );
                      })}
                    </div>
                  ))}
                  {filters.size > 0 ? (
                    <>
                      <DropdownMenuSeparator />
                      <DropdownMenuItem onSelect={() => setFilters(new Set())}>
                        <X /> Clear filters
                      </DropdownMenuItem>
                    </>
                  ) : null}
                </DropdownMenuContent>
              </DropdownMenu>

              <DropdownMenu>
                <DropdownMenuTrigger className={TOOL_BTN}>
                  {view === "grid" ? <LayoutGrid className="size-4" aria-hidden /> : <List className="size-4" aria-hidden />}
                  View
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end" className="w-52">
                  <DropdownMenuLabel className="flex items-center gap-1.5">
                    <ArrowDownUp className="size-3.5" aria-hidden /> Sort by
                  </DropdownMenuLabel>
                  <DropdownMenuRadioGroup value={sort} onValueChange={(v) => setSort(v as Sort)}>
                    {SORTS.map((s) => (
                      <DropdownMenuRadioItem key={s.value} value={s.value}>
                        {s.label}
                      </DropdownMenuRadioItem>
                    ))}
                  </DropdownMenuRadioGroup>
                  <DropdownMenuSeparator />
                  <DropdownMenuLabel>Layout</DropdownMenuLabel>
                  <DropdownMenuRadioGroup value={view} onValueChange={(v) => setView(v as "grid" | "list")}>
                    <DropdownMenuRadioItem value="grid">
                      <LayoutGrid /> Grid
                    </DropdownMenuRadioItem>
                    <DropdownMenuRadioItem value="list">
                      <List /> List
                    </DropdownMenuRadioItem>
                  </DropdownMenuRadioGroup>
                </DropdownMenuContent>
              </DropdownMenu>
            </div>
          </div>

          {activeChips.length > 0 ? (
            <div className="flex flex-wrap items-center gap-1.5" aria-label="Active filters">
              {activeChips.map((c) => (
                <button
                  key={c.key}
                  type="button"
                  onClick={() => toggleFilter(c.key)}
                  className="inline-flex h-7 items-center gap-1.5 rounded-full bg-surface-3 pl-3 pr-2 text-[12.5px] font-medium transition-colors hover:bg-surface-2"
                  aria-label={`Remove filter ${c.label}`}
                >
                  {c.label}
                  <X className="size-3.5 text-muted-foreground" aria-hidden />
                </button>
              ))}
              <button type="button" onClick={() => setFilters(new Set())} className="ml-1 text-[12.5px] font-medium text-muted-foreground underline-offset-4 hover:text-foreground hover:underline">
                Clear all
              </button>
            </div>
          ) : null}
        </div>
      ) : null}

      {/* Content */}
      {projects.isPending ? (
        <div className="grid gap-x-5 gap-y-7 sm:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-4" aria-busy="true" aria-label="Loading projects">
          {[0, 1, 2, 3, 4, 5].map((i) => (
            <ProjectCardSkeleton key={i} style={{ opacity: 1 - i * 0.12 }} />
          ))}
        </div>
      ) : projects.isError ? (
        <Card>
          <ErrorState error={projects.error} onRetry={() => projects.refetch()} />
        </Card>
      ) : !hasProjects ? (
        <FirstProjectEmpty />
      ) : (
        <>
          {/* Folders (top level, when not searching or filtering) */}
          {showFolders ? (
            view === "grid" ? (
              <div className="mb-7 grid gap-3 sm:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-4" aria-label="Folders">
                {folders.map((f) => (
                  <div key={f.id} className="group relative flex items-center gap-3 rounded-xl border border-border bg-card p-3 transition-colors hover:border-border-strong hover:bg-surface-2">
                    <span className="grid size-10 shrink-0 place-items-center rounded-lg bg-surface-3 text-muted-foreground group-hover:text-foreground" aria-hidden>
                      <Folder className="size-5" />
                    </span>
                    <button type="button" onClick={() => setOpenFolderId(f.id)} className="min-w-0 flex-1 text-left outline-none after:absolute after:inset-0 after:rounded-xl focus-visible:after:ring-2 focus-visible:after:ring-ring">
                      <span className="block truncate text-[14px] font-semibold">{f.name}</span>
                      <span className="block text-[12.5px] text-subtle-foreground">
                        {countIn(f)} {countIn(f) === 1 ? "project" : "projects"}
                      </span>
                    </button>
                    <div className="relative z-10 opacity-0 transition-opacity group-hover:opacity-100 focus-within:opacity-100 has-data-[state=open]:opacity-100 [@media(hover:none)]:opacity-100">
                      <FolderMenu folder={f} onRename={() => setRenaming(f)} onDelete={() => setDeleting(f)} />
                    </div>
                  </div>
                ))}
              </div>
            ) : null
          ) : null}

          {visible.length === 0 && !(view === "list" && showFolders) ? (
            narrowing ? (
              <div className="flex flex-col items-center gap-2 rounded-2xl border border-dashed border-border-strong px-6 py-16 text-center">
                <SearchX className="size-6 text-muted-foreground" aria-hidden />
                <p className="mt-1 text-[16px] font-semibold">No projects match</p>
                <p className="max-w-sm text-[14px] text-muted-foreground">
                  {needle ? `Nothing matches “${q.trim()}”` : "Nothing matches these filters"}
                  {openFolder ? " in this folder" : ""}.
                </p>
                <Button variant="outline" size="sm" className="mt-2" onClick={clearAll}>
                  Clear search and filters
                </Button>
              </div>
            ) : openFolder ? (
              <div className="flex flex-col items-center gap-2 rounded-2xl border border-dashed border-border-strong px-6 py-16 text-center">
                <FolderOpen className="size-6 text-muted-foreground" aria-hidden />
                <p className="mt-1 text-[16px] font-semibold">This folder is empty</p>
                <p className="max-w-sm text-[14px] text-muted-foreground">Use a project&apos;s ⋯ menu to move it here.</p>
              </div>
            ) : (
              <p className="py-10 text-center text-[14px] text-muted-foreground">Every project is in a folder.</p>
            )
          ) : view === "grid" ? (
            <div className="stagger grid gap-x-5 gap-y-7 sm:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-4">
              {visible.map((p, i) => (
                <ProjectCard
                  key={p.id}
                  project={p}
                  task={taskByProject.get(p.id)}
                  index={i}
                  owner={owner}
                  meta={metaFor(p)}
                  actions={menuFor(p)}
                  pinned={pinned.includes(p.id)}
                  onTogglePin={() => togglePin(p.id)}
                />
              ))}
            </div>
          ) : (
            <Card className="overflow-hidden">
              <Table>
                <THead>
                  <TR>
                    <TH>Name</TH>
                    <TH className="hidden md:table-cell">Owner</TH>
                    <TH>Status</TH>
                    <TH className="hidden sm:table-cell">Created</TH>
                    <TH className="hidden lg:table-cell">Last edited</TH>
                    <TH className="w-20">
                      <span className="sr-only">Pin and folder options</span>
                    </TH>
                  </TR>
                </THead>
                <TBody>
                  {showFolders
                    ? folders.map((f) => (
                        <TR key={f.id}>
                          <TD className="py-2.5">
                            <button type="button" onClick={() => setOpenFolderId(f.id)} className="flex items-center gap-3 rounded-md text-left outline-none focus-visible:ring-2 focus-visible:ring-ring">
                              <span className="grid size-10 place-items-center rounded-xl bg-surface-3 text-muted-foreground" aria-hidden>
                                <Folder className="size-5" />
                              </span>
                              <span>
                                <span className="block font-medium">{f.name}</span>
                                <span className="block text-[12.5px] text-subtle-foreground">
                                  {countIn(f)} {countIn(f) === 1 ? "project" : "projects"}
                                </span>
                              </span>
                            </button>
                          </TD>
                          <TD className="hidden md:table-cell" />
                          <TD />
                          <TD className="hidden text-muted-foreground sm:table-cell">{formatRelative(f.createdAt)}</TD>
                          <TD className="hidden lg:table-cell" />
                          <TD>
                            <FolderMenu folder={f} onRename={() => setRenaming(f)} onDelete={() => setDeleting(f)} />
                          </TD>
                        </TR>
                      ))
                    : null}
                  {visible.map((p) => (
                    <TR key={p.id} className="group">
                      <TD className="py-2.5">
                        <Link href={`/projects/${p.id}/ide`} className="group flex min-w-0 items-center gap-3 rounded-md outline-none focus-visible:ring-2 focus-visible:ring-ring">
                          <ProjectThumb project={p} />
                          <span className="min-w-0">
                            <span className="block truncate font-medium group-hover:underline">{p.name}</span>
                            <span className="block truncate font-mono text-[12px] text-subtle-foreground">{p.packageName ?? "—"}</span>
                          </span>
                        </Link>
                      </TD>
                      <TD className="hidden md:table-cell">
                        {owner ? (
                          <span className="flex items-center gap-2 text-muted-foreground">
                            <Avatar name={owner.name} src={owner.avatarUrl} className="size-6 ring-0 [&_span]:text-[10px]" />
                            <span className="truncate">{owner.name}</span>
                          </span>
                        ) : null}
                      </TD>
                      <TD>
                        {p.activeTaskCount > 0 ? (
                          <span className="text-[13px]">
                            <CardStatus project={p} task={taskByProject.get(p.id)} />
                          </span>
                        ) : p.lastBuild ? (
                          <BuildStatusBadge status={p.lastBuild.status} />
                        ) : (
                          <Badge tone="neutral">No builds</Badge>
                        )}
                      </TD>
                      <TD className="hidden text-muted-foreground sm:table-cell">{formatRelative(p.createdAt)}</TD>
                      <TD className="hidden text-muted-foreground lg:table-cell">{formatRelative(p.updatedAt)}</TD>
                      <TD>
                        <div className="flex items-center justify-end gap-1">
                          <PinButton pinned={pinned.includes(p.id)} name={p.name} onToggle={() => togglePin(p.id)} />
                          {menuFor(p)}
                        </div>
                      </TD>
                    </TR>
                  ))}
                </TBody>
              </Table>
            </Card>
          )}
        </>
      )}

      {/* Folder dialogs */}
      <FolderNameDialog
        open={!!creating}
        onOpenChange={(o) => !o && setCreating(null)}
        title="New folder"
        submitLabel="Create folder"
        onSubmit={(name) => {
          const id = create(name);
          if (creating?.moveProjectId) move(creating.moveProjectId, id);
          setCreating(null);
        }}
      />
      <FolderNameDialog
        open={!!renaming}
        onOpenChange={(o) => !o && setRenaming(null)}
        title="Rename folder"
        submitLabel="Save"
        initial={renaming?.name ?? ""}
        onSubmit={(name) => {
          if (renaming) rename(renaming.id, name);
          setRenaming(null);
        }}
      />
      <ConfirmDialog
        open={!!deleting}
        onOpenChange={(o) => !o && setDeleting(null)}
        title={`Delete folder “${deleting?.name ?? ""}”?`}
        description="Projects inside it move back to Projects. No project is deleted."
        confirmLabel="Delete folder"
        destructive
        onConfirm={() => {
          if (deleting) {
            remove(deleting.id);
            if (openFolderId === deleting.id) setOpenFolderId(null);
          }
          setDeleting(null);
        }}
      />
    </PageBody>
  );
}
