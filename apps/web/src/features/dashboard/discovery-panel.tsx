"use client";

import Link from "next/link";
import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import type { AgentTask, Project } from "@apppilot/contracts";
import { ArrowRight, ArrowUp, FolderKanban, History, Search, Sparkles } from "lucide-react";
import { EmptyState, ErrorState } from "@/components/states/states";
import { Button } from "@/components/ui/button";
import { Card, Kbd, Skeleton } from "@/components/ui/primitives";
import { NewProjectCard, PROJECT_CARD_SKELETON, ProjectCard } from "@/features/projects/project-card";
import { useAgentTasks, useProjects } from "@/lib/api/hooks";
import { cn } from "@/lib/utils";
import { useRecentProjects } from "@/stores/recent-projects";

type DiscoveryTab = "projects" | "recent" | "templates" | "search";

const TABS: { id: Exclude<DiscoveryTab, "search">; label: string }[] = [
  { id: "projects", label: "My projects" },
  { id: "recent", label: "Recently viewed" },
  { id: "templates", label: "Templates" },
];

const PILL =
  "inline-flex h-9 shrink-0 items-center gap-1.5 rounded-full border px-3.5 text-[13.5px] transition-colors duration-150 outline-none focus-visible:ring-2 focus-visible:ring-ring";
const PILL_IDLE = "border-transparent font-medium text-muted-foreground hover:text-foreground";
const PILL_ON = "border-border-strong bg-card font-semibold text-foreground shadow-[0_1px_2px_rgb(21_17_43/0.12)]";

/** Card grid: 1 → 2 → 4 columns; on phones it becomes a horizontal snap rail. */
const GRID =
  "stagger grid gap-4 sm:grid-cols-2 xl:grid-cols-4 max-sm:flex max-sm:snap-x max-sm:snap-mandatory max-sm:overflow-x-auto max-sm:pb-2 max-sm:*:w-[84%] max-sm:*:shrink-0 max-sm:*:snap-start";

const noopSubscribe = () => () => {};

function matches(q: string, ...fields: (string | null | undefined)[]) {
  return fields.some((f) => f?.toLowerCase().includes(q));
}

function TemplateCard({ prompt, index, onUse }: { prompt: string; index: number; onUse: (prompt: string) => void }) {
  return (
    <button
      type="button"
      onClick={() => onUse(prompt)}
      style={{ "--i": index } as React.CSSProperties}
      className="group flex min-w-0 flex-col gap-3 rounded-[12px] border border-border bg-card p-4 text-left transition-[border-color,box-shadow] duration-150 hover:border-primary/50 hover:shadow-[0_10px_30px_-16px_var(--brand-glow)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
    >
      <span className="grid size-8 place-items-center rounded-sm bg-ai-soft text-ai" aria-hidden>
        <Sparkles className="size-4" />
      </span>
      <span className="min-h-10.5 text-[14px] leading-normal text-foreground">{prompt}</span>
      <span className="mt-auto inline-flex items-center gap-1.5 text-[13px] font-semibold text-primary">
        Use this prompt
        <ArrowUp className="size-3.5 transition-transform group-hover:-translate-y-0.5" aria-hidden />
      </span>
    </button>
  );
}

function ProjectGrid({ projects, taskByProject, withNew }: { projects: Project[]; taskByProject: Map<string, AgentTask>; withNew?: boolean }) {
  return (
    <div className={GRID}>
      {projects.map((p, i) => (
        <ProjectCard key={p.id} project={p} task={taskByProject.get(p.id)} index={i} />
      ))}
      {withNew ? <NewProjectCard index={projects.length} /> : null}
    </div>
  );
}

/**
 * The dashboard's discovery panel: search, the user's projects, recently viewed
 * projects (this device) and starter templates, in one panel below the build prompt.
 */
export function DiscoveryPanel({ templates, onUseTemplate }: { templates: readonly string[]; onUseTemplate: (prompt: string) => void }) {
  const projects = useProjects();
  // Same query as "Agent tasks running" (shared cache), used for each card's status.
  const activeTasks = useAgentTasks({ status: "active" });
  const recentViews = useRecentProjects((s) => s.views);
  const [tab, setTab] = useState<DiscoveryTab>("projects");
  const [query, setQuery] = useState("");
  const isMac = useSyncExternalStore(
    noopSubscribe,
    () => /Mac|iPhone|iPad/.test(navigator.userAgent),
    () => false,
  );
  const searchRef = useRef<HTMLInputElement>(null);

  const openSearch = () => {
    setTab("search");
    requestAnimationFrame(() => searchRef.current?.focus());
  };

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && !e.altKey && !e.shiftKey && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setTab("search");
        requestAnimationFrame(() => searchRef.current?.focus());
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const taskByProject = new Map<string, AgentTask>();
  for (const t of activeTasks.data ?? []) if (!taskByProject.has(t.projectId)) taskByProject.set(t.projectId, t);

  const all = projects.data?.items ?? [];
  const byId = new Map(all.map((p) => [p.id, p]));
  const latest = [...all].sort((a, b) => b.updatedAt.localeCompare(a.updatedAt)).slice(0, 3);
  const recent = recentViews.flatMap((v) => byId.get(v.id) ?? []).slice(0, 4);
  const q = query.trim().toLowerCase();
  const projectHits = q ? all.filter((p) => matches(q, p.name, p.description, p.packageName)) : [];
  const templateHits = q ? templates.filter((t) => t.toLowerCase().includes(q)) : [];

  const loading = projects.isPending ? (
    <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4" aria-busy="true" aria-label="Loading projects">
      {[0, 1, 2, 3].map((i) => (
        <Skeleton key={i} className={cn(PROJECT_CARD_SKELETON, i > 0 && "max-sm:hidden")} />
      ))}
    </div>
  ) : projects.isError ? (
    <Card>
      <ErrorState error={projects.error} onRetry={() => projects.refetch()} />
    </Card>
  ) : null;

  const hint = (text: string) => <p className="mb-3 text-[13.5px] text-muted-foreground">{text}</p>;

  return (
    <div className="relative isolate mt-14">
      <div aria-hidden className="discovery-glow pointer-events-none absolute inset-x-0 -top-12 -z-10 h-72" />
      <section aria-label="Your projects and templates" className="discovery-panel relative rounded-2xl border border-border bg-surface p-3 sm:p-5">
        <span aria-hidden className="hairline-top absolute inset-x-[12%] -top-px h-px" />

        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex min-w-0 max-w-full items-center gap-0.5 overflow-x-auto rounded-full border border-border-strong bg-surface-2 p-1">
            {tab === "search" ? (
              <div className="relative flex min-w-0 flex-1 shrink-0 items-center sm:flex-none">
                <label htmlFor="discovery-search" className="sr-only">
                  Search projects and templates
                </label>
                <Search className="pointer-events-none absolute left-3 size-3.5 text-subtle-foreground" aria-hidden />
                <input
                  id="discovery-search"
                  ref={searchRef}
                  type="search"
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Escape") {
                      e.preventDefault();
                      if (query) setQuery("");
                      else setTab("projects");
                    }
                  }}
                  placeholder="Search projects and templates"
                  autoComplete="off"
                  className="h-9 w-full min-w-40 rounded-full border border-ring bg-card pl-8 pr-3 text-[13.5px] text-foreground shadow-[0_0_0_3px_var(--primary-soft)] outline-none placeholder:text-subtle-foreground sm:w-64 sm:pr-16 [&::-webkit-search-cancel-button]:hidden"
                />
                <span className="pointer-events-none absolute right-2.5 hidden gap-0.5 sm:flex" aria-hidden>
                  <Kbd>{isMac ? "⌘" : "Ctrl"}</Kbd>
                  <Kbd>K</Kbd>
                </span>
              </div>
            ) : (
              <button type="button" onClick={openSearch} className={cn(PILL, PILL_IDLE)} aria-keyshortcuts="Control+K Meta+K">
                <Search className="size-3.5" aria-hidden />
                Search
              </button>
            )}
            <div role="tablist" aria-label="Discover" className="flex items-center gap-0.5">
              {TABS.map((t) => (
                <button
                  key={t.id}
                  type="button"
                  role="tab"
                  id={`discovery-tab-${t.id}`}
                  aria-selected={tab === t.id}
                  aria-controls="discovery-body"
                  onClick={() => {
                    setTab(t.id);
                    setQuery("");
                  }}
                  className={cn(PILL, tab === t.id ? PILL_ON : PILL_IDLE)}
                >
                  {t.label}
                </button>
              ))}
            </div>
          </div>
          <Link
            href="/projects"
            className="group inline-flex h-9 shrink-0 items-center gap-1.5 self-end rounded-full px-2 text-[13.5px] font-semibold text-foreground transition-colors hover:text-primary sm:self-auto"
          >
            Browse all
            <ArrowRight className="size-4 transition-transform group-hover:translate-x-0.5" aria-hidden />
          </Link>
        </div>

        <div id="discovery-body" role={tab === "search" ? "region" : "tabpanel"} aria-label={tab === "search" ? "Search results" : undefined} aria-labelledby={tab === "search" ? undefined : `discovery-tab-${tab}`} className="mt-4 min-h-44 sm:mt-5">
          {tab === "projects" ? (
            <>
              {hint("Your most recently edited projects.")}
              {loading ??
                (latest.length === 0 ? (
                  <Card className="overflow-hidden">
                    <EmptyState
                      icon={<FolderKanban />}
                      title="No projects yet"
                      action={
                        <Button asChild>
                          <Link href="/projects/new">
                            <Sparkles /> Create your first app
                          </Link>
                        </Button>
                      }
                    >
                      Describe an app above and AppPilot will generate your first Gradle project.
                    </EmptyState>
                  </Card>
                ) : (
                  <ProjectGrid projects={latest} taskByProject={taskByProject} withNew />
                ))}
            </>
          ) : tab === "recent" ? (
            <>
              {hint("Projects you opened recently on this device.")}
              {loading ??
                (recent.length === 0 ? (
                  <Card className="overflow-hidden">
                    <EmptyState compact icon={<History />} title="Nothing viewed yet">
                      Projects you open will show up here.
                    </EmptyState>
                  </Card>
                ) : (
                  <ProjectGrid projects={recent} taskByProject={taskByProject} />
                ))}
            </>
          ) : tab === "templates" ? (
            <>
              {hint("Starter prompts. Pick one to fill the build prompt above.")}
              <div className={GRID}>
                {templates.map((t, i) => (
                  <TemplateCard key={t} prompt={t} index={i} onUse={onUseTemplate} />
                ))}
              </div>
            </>
          ) : !q ? (
            hint("Type to search your projects and starter templates.")
          ) : (
            <div aria-live="polite">
              {projectHits.length > 0 ? (
                <div className="mb-5">
                  <p className="mb-2.5 text-[12px] font-semibold uppercase tracking-[0.06em] text-subtle-foreground">Projects · {projectHits.length}</p>
                  <ProjectGrid projects={projectHits.slice(0, 8)} taskByProject={taskByProject} />
                </div>
              ) : null}
              {templateHits.length > 0 ? (
                <div>
                  <p className="mb-2.5 text-[12px] font-semibold uppercase tracking-[0.06em] text-subtle-foreground">Templates · {templateHits.length}</p>
                  <div className={GRID}>
                    {templateHits.map((t, i) => (
                      <TemplateCard key={t} prompt={t} index={i} onUse={onUseTemplate} />
                    ))}
                  </div>
                </div>
              ) : null}
              {projectHits.length === 0 && templateHits.length === 0 ? (
                projects.isPending ? (
                  loading
                ) : (
                  <Card className="overflow-hidden">
                    <EmptyState compact icon={<Search />} title="No matches">
                      Nothing matches &ldquo;{query.trim()}&rdquo;.
                    </EmptyState>
                  </Card>
                )
              ) : null}
            </div>
          )}
        </div>
      </section>
    </div>
  );
}
