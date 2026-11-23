"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import type { AgentTask, Project } from "@apppilot/contracts";
import {
  Code2,
  FileArchive,
  Hammer,
  LayoutGrid,
  List,
  MessageSquareText,
  MoreHorizontal,
  Package,
  Plus,
  Search,
  Settings,
  SearchX,
  Sparkles,
  Trash2,
  X,
  type LucideIcon,
} from "lucide-react";
import { toast } from "sonner";
import { PageBody } from "@/components/layout/page";
import { ErrorState } from "@/components/states/states";
import { BuildStatusBadge } from "@/components/status/status-badge";
import { Button } from "@/components/ui/button";
import {
  ConfirmDialog,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
  Select,
} from "@/components/ui/overlays";
import { Badge, Card, Input, Skeleton, Table, TBody, TD, TH, THead, TR } from "@/components/ui/primitives";
import { errorMessage } from "@/lib/api/errors";
import { useAgentTasks, useDeleteProject, useProjects } from "@/lib/api/hooks";
import { cn, formatBytes, formatRelative } from "@/lib/utils";
import { useUiStore } from "@/stores/ui-store";
import { ProjectTechBadges } from "./project-meta";
import { NewProjectCard, PROJECT_CARD_SKELETON, ProjectCard } from "./project-card";
import { ProjectThumb } from "./project-preview";

type SourceFilter = "all" | Project["source"];
type Sort = "updated" | "name" | "created";

const SOURCE_TABS: { value: SourceFilter; label: string; icon: LucideIcon }[] = [
  { value: "all", label: "All", icon: Sparkles },
  { value: "prompt", label: "From prompt", icon: MessageSquareText },
  { value: "android_zip", label: "Imported", icon: FileArchive },
  { value: "apk", label: "APK analyses", icon: Package },
];

function ProjectActions({ project, onDelete, className }: { project: Project; onDelete: () => void; className?: string }) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="subtle" size="icon-sm" className={className} aria-label={`Actions for ${project.name}`}>
          <MoreHorizontal />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        <DropdownMenuItem asChild>
          <Link href={`/projects/${project.id}/ide`}>
            <Code2 /> Open in IDE
          </Link>
        </DropdownMenuItem>
        <DropdownMenuItem asChild>
          <Link href={`/projects/${project.id}/builds`}>
            <Hammer /> Builds
          </Link>
        </DropdownMenuItem>
        <DropdownMenuItem asChild>
          <Link href={`/projects/${project.id}/settings`}>
            <Settings /> Settings
          </Link>
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem variant="destructive" onSelect={onDelete}>
          <Trash2 /> Delete project
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

/** First-run empty state: three floating device mockups and one clear next step. */
function FirstProjectEmpty() {
  const phones = [
    { hue: 275, rot: "-rotate-12", pos: "left-[6%] top-10", delay: "0s" },
    { hue: 330, rot: "rotate-0", pos: "left-1/2 -translate-x-1/2 top-0", delay: "1.2s" },
    { hue: 200, rot: "rotate-12", pos: "right-[6%] top-10", delay: "2.4s" },
  ];
  return (
    <div className="relative isolate overflow-hidden rounded-3xl border border-border bg-card px-6 py-14 text-center shadow-card sm:py-20">
      <div aria-hidden className="absolute inset-0 -z-10">
        <div className="absolute left-1/2 top-0 h-80 w-[36rem] max-w-full -translate-x-1/2 rounded-full bg-brand opacity-25 blur-[100px]" />
        <div className="dot-grid absolute inset-0 opacity-30 [mask-image:radial-gradient(ellipse_60%_60%_at_50%_30%,black,transparent)]" />
      </div>
      <div aria-hidden className="relative mx-auto h-56 w-full max-w-md">
        {phones.map((p, i) => (
          <div key={i} className={cn("absolute w-24 animate-float", p.pos)} style={{ animationDelay: p.delay }}>
            <div className={cn("h-40 rounded-2xl border border-white/20 bg-background/80 p-2 shadow-[0_24px_50px_-18px_rgb(0_0_0/0.55)] backdrop-blur", p.rot)}>
              <div
                className="grid h-10 place-items-center rounded-xl text-white"
                style={{ backgroundImage: `linear-gradient(135deg, oklch(0.62 0.2 ${p.hue}), oklch(0.5 0.22 ${p.hue + 70}))` }}
              >
                {i === 1 ? <Sparkles className="size-4" /> : null}
              </div>
              <div className="mt-2 grid gap-1.5">
                <i className="h-2 w-full rounded-full bg-foreground/15" />
                <i className="h-2 w-2/3 rounded-full bg-foreground/10" />
                <i className="h-9 w-full rounded-lg bg-foreground/[0.07]" />
                <i className="h-9 w-full rounded-lg bg-foreground/[0.07]" />
              </div>
            </div>
          </div>
        ))}
      </div>
      <h2 className="mt-4 text-balance font-display text-3xl font-semibold tracking-[-0.03em] sm:text-4xl">
        Your first app is <span className="text-brand">one sentence away</span>
      </h2>
      <p className="mx-auto mt-3 max-w-md text-pretty text-[15.5px] leading-relaxed text-muted-foreground">
        Describe an app, upload an Android Studio project, or inspect an APK. Everything you create shows up here.
      </p>
      <div className="mt-8 flex flex-wrap items-center justify-center gap-3">
        <Button asChild size="lg">
          <Link href="/projects/new">
            <Sparkles /> Create New Project
          </Link>
        </Button>
        <Button asChild size="lg" variant="outline">
          <Link href="/projects/new?method=zip">
            <FileArchive /> Upload a project
          </Link>
        </Button>
      </div>
    </div>
  );
}

function GridSkeleton() {
  return (
    <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3" aria-busy="true" aria-label="Loading projects">
      {[0, 1, 2, 3, 4, 5].map((i) => (
        <Skeleton key={i} className={PROJECT_CARD_SKELETON} style={{ opacity: 1 - i * 0.1 }} />
      ))}
    </div>
  );
}

export function ProjectsScreen() {
  const projects = useProjects();
  const del = useDeleteProject();
  const view = useUiStore((s) => s.projectsView);
  const setView = useUiStore((s) => s.setProjectsView);
  const [q, setQ] = useState("");
  const [source, setSource] = useState<SourceFilter>("all");
  const [sort, setSort] = useState<Sort>("updated");
  const [toDelete, setToDelete] = useState<Project | null>(null);
  const [confirmName, setConfirmName] = useState("");

  const all = projects.data?.items ?? [];

  const filtered = useMemo(() => {
    const items = projects.data?.items ?? [];
    const needle = q.trim().toLowerCase();
    return items
      .filter((p) => source === "all" || p.source === source)
      .filter((p) => !needle || p.name.toLowerCase().includes(needle) || (p.packageName ?? "").toLowerCase().includes(needle))
      .sort((a, b) =>
        sort === "name" ? a.name.localeCompare(b.name) : sort === "created" ? b.createdAt.localeCompare(a.createdAt) : b.updatedAt.localeCompare(a.updatedAt),
      );
  }, [projects.data, q, source, sort]);

  const countFor = (s: SourceFilter) => (s === "all" ? all.length : all.filter((p) => p.source === s).length);
  const running = all.reduce((n, p) => n + p.activeTaskCount, 0);
  // The live step label on each card comes from the active agent tasks (same query as the dashboard).
  const activeTasks = useAgentTasks({ status: "active" }, { enabled: running > 0 });
  const taskByProject = useMemo(() => {
    const m = new Map<string, AgentTask>();
    for (const t of activeTasks.data ?? []) if (!m.has(t.projectId)) m.set(t.projectId, t);
    return m;
  }, [activeTasks.data]);
  const filtering = q.trim() !== "" || source !== "all";

  return (
    <PageBody className="max-w-[1280px]">
      <header className="flex animate-fade-up flex-wrap items-end justify-between gap-4 pb-8">
        <div className="min-w-0">
          <h1 className="text-[clamp(2rem,4vw,2.75rem)] font-semibold leading-tight tracking-[-0.035em]">Your projects</h1>
          <p className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[15px] text-muted-foreground">
            <span>Generated apps, imported Android Studio projects and APK analyses.</span>
            {projects.data ? (
              <span className="inline-flex items-center gap-2 text-[13px]">
                <Badge tone="neutral">{all.length} total</Badge>
                {running > 0 ? (
                  <Badge tone="ai">
                    <span className="size-1.5 animate-glow rounded-full bg-ai" aria-hidden /> {running} agent{running === 1 ? "" : "s"} running
                  </Badge>
                ) : null}
              </span>
            ) : null}
          </p>
        </div>
        <Button asChild size="lg">
          <Link href="/projects/new">
            <Plus /> New project
          </Link>
        </Button>
      </header>

      {/* Hide the toolbar when there is nothing to filter yet. */}
      {projects.isPending || all.length > 0 || projects.isError ? (
        <div className="mb-6 grid animate-fade-up gap-3 [animation-delay:80ms]">
          <div className="flex flex-wrap items-center gap-2">
            <div className="relative min-w-60 flex-1 sm:max-w-md">
              <Search className="pointer-events-none absolute left-3.5 top-1/2 size-4 -translate-y-1/2 text-subtle-foreground" aria-hidden />
              <Input
                value={q}
                onChange={(e) => setQ(e.target.value)}
                placeholder="Search by name or package"
                className="h-10 rounded-full bg-card pl-10 pr-9"
                aria-label="Search projects"
              />
              {q ? (
                <button
                  type="button"
                  onClick={() => setQ("")}
                  aria-label="Clear search"
                  className="absolute right-2.5 top-1/2 grid size-6 -translate-y-1/2 place-items-center rounded-full text-muted-foreground transition-colors hover:bg-surface-3 hover:text-foreground"
                >
                  <X className="size-3.5" />
                </button>
              ) : null}
            </div>
            <Select<Sort>
              aria-label="Sort"
              className="h-10 w-44 rounded-full"
              value={sort}
              onValueChange={setSort}
              options={[
                { value: "updated", label: "Recently updated" },
                { value: "created", label: "Recently created" },
                { value: "name", label: "Name" },
              ]}
            />
            <div className="ml-auto flex rounded-full border border-input bg-card p-1" role="group" aria-label="View">
              <Button variant={view === "grid" ? "secondary" : "ghost"} size="icon-sm" className="rounded-full" aria-pressed={view === "grid"} aria-label="Grid view" onClick={() => setView("grid")}>
                <LayoutGrid />
              </Button>
              <Button variant={view === "list" ? "secondary" : "ghost"} size="icon-sm" className="rounded-full" aria-pressed={view === "list"} aria-label="List view" onClick={() => setView("list")}>
                <List />
              </Button>
            </div>
          </div>

          <div className="flex gap-2 overflow-x-auto pb-1" role="group" aria-label="Filter by source">
            {SOURCE_TABS.map((t) => {
              const active = source === t.value;
              return (
                <button
                  key={t.value}
                  type="button"
                  aria-pressed={active}
                  onClick={() => setSource(t.value)}
                  className={cn(
                    "inline-flex h-9 shrink-0 items-center gap-2 rounded-full border px-3.5 text-[13.5px] font-medium transition-all duration-200",
                    active
                      ? "border-transparent bg-brand text-white shadow-[0_6px_18px_-8px_var(--brand-glow)]"
                      : "border-border-strong bg-card text-muted-foreground hover:border-primary/50 hover:text-foreground",
                  )}
                >
                  <t.icon className="size-3.5" aria-hidden />
                  {t.label}
                  {projects.data ? (
                    <span className={cn("rounded-full px-1.5 text-[12px] tabular-nums", active ? "bg-white/20" : "bg-surface-3")}>{countFor(t.value)}</span>
                  ) : null}
                </button>
              );
            })}
          </div>
        </div>
      ) : null}

      {projects.isPending ? (
        view === "grid" ? (
          <GridSkeleton />
        ) : (
          <Card className="grid gap-2 p-4" aria-busy="true" aria-label="Loading projects">
            {[0, 1, 2, 3, 4].map((i) => (
              <Skeleton key={i} className="h-14 rounded-xl" style={{ opacity: 1 - i * 0.15 }} />
            ))}
          </Card>
        )
      ) : projects.isError ? (
        <Card>
          <ErrorState error={projects.error} onRetry={() => projects.refetch()} />
        </Card>
      ) : all.length === 0 ? (
        <FirstProjectEmpty />
      ) : filtered.length === 0 ? (
        <Card className="overflow-hidden">
          <div className="flex flex-col items-center gap-2 px-6 py-16 text-center">
            <span className="grid size-14 place-items-center rounded-2xl border border-border-strong bg-surface-2 text-muted-foreground shadow-card">
              <SearchX className="size-6" aria-hidden />
            </span>
            <p className="mt-2 font-display text-[18px] font-semibold tracking-tight">No projects match</p>
            <p className="max-w-sm text-[14px] text-muted-foreground">
              {q.trim() ? `Nothing matches “${q.trim()}”` : "Nothing matches this filter"}. Try a different name or clear your filters.
            </p>
            <Button
              variant="outline"
              size="sm"
              className="mt-3"
              onClick={() => {
                setQ("");
                setSource("all");
              }}
            >
              Clear filters
            </Button>
          </div>
        </Card>
      ) : view === "grid" ? (
        <div className="stagger grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {filtered.map((p, i) => (
            <ProjectCard
              key={p.id}
              project={p}
              task={taskByProject.get(p.id)}
              index={i}
              actions={<ProjectActions project={p} onDelete={() => setToDelete(p)} className="text-muted-foreground hover:text-foreground" />}
            />
          ))}
          {!filtering ? <NewProjectCard index={filtered.length} /> : null}
        </div>
      ) : (
        <Card className="animate-fade-up overflow-hidden">
          <Table>
            <THead>
              <TR>
                <TH>Name</TH>
                <TH className="hidden md:table-cell">Stack</TH>
                <TH>Last build</TH>
                <TH className="hidden sm:table-cell">Storage</TH>
                <TH className="hidden sm:table-cell">Updated</TH>
                <TH className="w-10">
                  <span className="sr-only">Actions</span>
                </TH>
              </TR>
            </THead>
            <TBody>
              {filtered.map((p) => (
                <TR key={p.id} className="hover:bg-primary-soft">
                  <TD className="py-3">
                    <Link href={`/projects/${p.id}/ide`} className="group flex items-center gap-3">
                      <ProjectThumb project={p} />
                      <span className="min-w-0">
                        <span className="flex items-center gap-2">
                          <span className="truncate font-medium group-hover:text-primary">{p.name}</span>
                          {p.activeTaskCount > 0 ? <Badge tone="ai">{p.activeTaskCount} running</Badge> : null}
                        </span>
                        <span className="block truncate font-mono text-[12.5px] text-muted-foreground">{p.packageName ?? "—"}</span>
                      </span>
                    </Link>
                  </TD>
                  <TD className="hidden md:table-cell">
                    <ProjectTechBadges project={p} />
                  </TD>
                  <TD>{p.lastBuild ? <BuildStatusBadge status={p.lastBuild.status} /> : <span className="text-[13px] text-muted-foreground">None</span>}</TD>
                  <TD className="hidden tabular-nums text-muted-foreground sm:table-cell">{formatBytes(p.storageBytes)}</TD>
                  <TD className="hidden text-muted-foreground sm:table-cell">{formatRelative(p.updatedAt)}</TD>
                  <TD>
                    <ProjectActions project={p} onDelete={() => setToDelete(p)} />
                  </TD>
                </TR>
              ))}
            </TBody>
          </Table>
        </Card>
      )}

      <ConfirmDialog
        open={!!toDelete}
        onOpenChange={(o) => {
          if (!o) {
            setToDelete(null);
            setConfirmName("");
          }
        }}
        title={`Delete ${toDelete?.name ?? "project"}?`}
        description="This deletes the project's files, builds, artifacts and agent history. It can't be undone."
        confirmLabel="Delete project"
        destructive
        loading={del.isPending}
        onConfirm={() => {
          if (!toDelete || confirmName !== toDelete.name) return;
          del.mutate(toDelete.id, {
            onSuccess: () => {
              toast.success(`Deleted ${toDelete.name}`);
              setToDelete(null);
              setConfirmName("");
            },
            onError: (e) => toast.error(errorMessage(e)),
          });
        }}
      >
        <label className="grid gap-1.5 text-[14px]">
          <span>
            Type <span className="font-mono">{toDelete?.name}</span> to confirm
          </span>
          <Input value={confirmName} onChange={(e) => setConfirmName(e.target.value)} autoFocus />
        </label>
      </ConfirmDialog>
    </PageBody>
  );
}
