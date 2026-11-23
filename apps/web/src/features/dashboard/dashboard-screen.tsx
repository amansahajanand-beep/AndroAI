"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useRef, useState } from "react";
import type { ActivityEvent, Build } from "@apppilot/contracts";
import {
  ArrowUp,
  Bot,
  CheckCircle2,
  FileArchive,
  FolderPlus,
  Hammer,
  Package,
  Sparkles,
  TestTube2,
  XCircle,
  type LucideIcon,
} from "lucide-react";
import { PageBody, Meter, SectionTitle } from "@/components/layout/page";
import { EmptyState, ErrorState, QueryView } from "@/components/states/states";
import { AgentStatusBadge, BuildStatusBadge } from "@/components/status/status-badge";
import { Card, CardContent, Skeleton } from "@/components/ui/primitives";
import { useActivity, useAgentTasks, useBuilds, useProjects, useSession, useUsage } from "@/lib/api/hooks";
import { cn, formatBytes, formatDuration, formatNumber, formatRelative } from "@/lib/utils";
import { DiscoveryPanel } from "./discovery-panel";

const ACTIVITY_ICON: Record<ActivityEvent["kind"], LucideIcon> = {
  project_created: FolderPlus,
  agent_task_started: Bot,
  agent_task_completed: Sparkles,
  agent_task_failed: XCircle,
  build_succeeded: CheckCircle2,
  build_failed: XCircle,
  tests_passed: TestTube2,
  tests_failed: TestTube2,
  files_changed: Sparkles,
};

const IDEAS = [
  "A habit tracker with daily reminders and a weekly streak chart",
  "An expense splitter for trips with offline support",
  "A recipe app with a shopping list and a cooking timer",
  "A trail finder with maps, filters and saved hikes",
];

function greeting() {
  const h = new Date().getHours();
  return h < 5 ? "Working late" : h < 12 ? "Good morning" : h < 18 ? "Good afternoon" : "Good evening";
}

/* ------------------------------------------------------------------ */
/* Hero: the prompt is the page.                                       */
/* ------------------------------------------------------------------ */

function PromptHero({
  firstName,
  text,
  setText,
  inputRef: ref,
}: {
  firstName?: string;
  text: string;
  setText: (text: string) => void;
  inputRef: React.RefObject<HTMLTextAreaElement | null>;
}) {
  const router = useRouter();

  const submit = () => {
    const q = new URLSearchParams({ method: "prompt" });
    if (text.trim()) q.set("description", text.trim());
    router.push(`/projects/new?${q}`);
  };

  return (
    <section aria-label="Start a new app" className="relative mx-auto max-w-3xl pb-4 pt-2 text-center sm:pt-8">
      <p className="animate-fade-up">
        <span className="inline-flex items-center gap-2 rounded-full border border-border-strong bg-surface/70 py-1 pl-1.5 pr-3.5 text-[13px] text-muted-foreground backdrop-blur">
          <span className="grid size-5 place-items-center rounded-full bg-brand text-white">
            <Sparkles className="size-3" aria-hidden />
          </span>
          {greeting()}
          {firstName ? `, ${firstName}` : ""}
        </span>
      </p>
      <h1 className="mt-5 animate-fade-up text-balance text-[clamp(2.25rem,5.5vw,3.75rem)] font-semibold leading-[1.02] tracking-[-0.04em] [animation-delay:80ms]">
        What will you <span className="text-brand animate-pan">build</span> today?
      </h1>
      <p className="mx-auto mt-4 max-w-xl animate-fade-up text-pretty text-[16px] leading-relaxed text-muted-foreground [animation-delay:160ms]">
        Describe your Android app. AppPilot plans it, writes the code, runs Gradle and asks for your review.
      </p>

      <form
        className="group/prompt relative mt-8 animate-fade-up text-left [animation-delay:240ms]"
        onSubmit={(e) => {
          e.preventDefault();
          submit();
        }}
      >
        <div aria-hidden className="absolute -inset-4 -z-10 rounded-[2.5rem] bg-brand opacity-25 blur-3xl transition-opacity duration-500 group-focus-within/prompt:opacity-45" />
        <div className="rounded-[26px] bg-linear-to-b from-brand-2/60 via-border-strong to-border p-px transition-all duration-300 focus-within:from-brand-1 focus-within:via-brand-2 focus-within:to-brand-3">
          <div className="rounded-[25px] bg-card p-3 sm:p-4">
            <label htmlFor="quick-prompt" className="sr-only">
              Describe the app
            </label>
            <textarea
              id="quick-prompt"
              ref={ref}
              value={text}
              onChange={(e) => setText(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                  e.preventDefault();
                  submit();
                }
              }}
              rows={3}
              placeholder="Ask AppPilot to build a habit tracker with daily reminders and a weekly streak chart…"
              className="block min-h-[96px] w-full resize-none bg-transparent px-2 py-1.5 text-[16px] leading-relaxed text-foreground outline-none placeholder:text-subtle-foreground"
            />
            <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
              <div className="flex flex-wrap items-center gap-1.5">
                <Link
                  href="/projects/new?method=zip"
                  className="inline-flex h-8 items-center gap-1.5 rounded-full border border-border-strong px-3 text-[13px] text-muted-foreground transition-colors hover:border-primary/50 hover:bg-primary-soft hover:text-foreground"
                >
                  <FileArchive className="size-3.5" aria-hidden /> Upload project
                </Link>
                <Link
                  href="/projects/new?method=apk"
                  className="inline-flex h-8 items-center gap-1.5 rounded-full border border-border-strong px-3 text-[13px] text-muted-foreground transition-colors hover:border-primary/50 hover:bg-primary-soft hover:text-foreground"
                >
                  <Package className="size-3.5" aria-hidden /> Analyze APK
                </Link>
              </div>
              <div className="flex items-center gap-3">
                <span className="hidden text-[12px] text-subtle-foreground sm:inline">Enter to continue · Shift+Enter for a new line</span>
                <button
                  type="submit"
                  aria-label="Continue"
                  className="grid size-10 place-items-center rounded-full bg-brand text-white shadow-[0_8px_22px_-8px_var(--brand-glow)] transition-all duration-200 hover:scale-105 hover:brightness-110 active:scale-95"
                >
                  <ArrowUp className="size-5" aria-hidden />
                </button>
              </div>
            </div>
          </div>
        </div>
      </form>

      <div className="mt-5 flex animate-fade-up flex-wrap justify-center gap-2 [animation-delay:320ms]" aria-label="Ideas">
        {IDEAS.map((idea) => (
          <button
            key={idea}
            type="button"
            onClick={() => {
              setText(idea);
              ref.current?.focus();
            }}
            className="max-w-full truncate rounded-full border border-border bg-surface/60 px-3.5 py-1.5 text-[13px] text-muted-foreground backdrop-blur transition-all duration-200 hover:-translate-y-0.5 hover:border-primary/50 hover:bg-primary-soft hover:text-foreground"
          >
            {idea.length > 42 ? `${idea.slice(0, 40)}…` : idea}
          </button>
        ))}
      </div>
    </section>
  );
}

/* ------------------------------------------------------------------ */
/* Builds, activity, usage, agents                                     */
/* ------------------------------------------------------------------ */

function BuildRow({ b, projectName }: { b: Build; projectName?: string }) {
  return (
    <Link
      href={`/projects/${b.projectId}/builds?build=${b.id}`}
      className="grid grid-cols-[1fr_auto] items-center gap-x-3 gap-y-0.5 px-5 py-3 transition-colors duration-150 hover:bg-primary-soft sm:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)_auto_auto]"
    >
      <span className="truncate text-[14px]">
        <span className="font-medium">{projectName ?? b.projectId}</span> <span className="text-muted-foreground">#{b.number}</span>
      </span>
      <span className="hidden truncate font-mono text-[13px] text-muted-foreground sm:block">{b.gradleTask}</span>
      <span className="hidden text-[13px] tabular-nums text-muted-foreground sm:block">
        {b.status === "running" ? "running" : formatDuration(b.durationMs)}
      </span>
      <BuildStatusBadge status={b.status} className="justify-self-end" />
    </Link>
  );
}

export function DashboardScreen() {
  const session = useSession();
  const projects = useProjects();
  const activeTasks = useAgentTasks({ status: "active" });
  const builds = useBuilds();
  const usage = useUsage();
  const activity = useActivity();

  const names = new Map(projects.data?.items.map((p) => [p.id, p.name]));
  const firstName = session.data?.user.name.split(" ")[0];

  // The build prompt lives here so a template in the discovery panel can fill it.
  const [prompt, setPrompt] = useState("");
  const promptRef = useRef<HTMLTextAreaElement>(null);
  const fillPrompt = (text: string) => {
    setPrompt(text);
    requestAnimationFrame(() => {
      const el = promptRef.current;
      if (!el) return;
      const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      el.scrollIntoView({ behavior: reduce ? "auto" : "smooth", block: "center" });
      el.focus({ preventScroll: true });
      el.setSelectionRange(text.length, text.length);
    });
  };

  return (
    <PageBody className="max-w-[1280px]">
      <PromptHero firstName={firstName} text={prompt} setText={setPrompt} inputRef={promptRef} />

      <DiscoveryPanel templates={IDEAS} onUseTemplate={fillPrompt} />

      <div className="mt-12 grid gap-6 lg:grid-cols-[minmax(0,1fr)_360px]">
        <div className="grid min-w-0 grid-cols-[minmax(0,1fr)] content-start gap-6">
          <section>
            <SectionTitle action={<Hammer className="size-4 text-muted-foreground" aria-hidden />}>Recent builds</SectionTitle>
            <Card className="overflow-hidden">
              <QueryView
                query={builds}
                compact
                isEmpty={(d) => d.length === 0}
                empty={<EmptyState compact title="No builds yet">Builds appear here after you or an agent run Gradle.</EmptyState>}
              >
                {(d) => (
                  <div className="divide-y divide-border">
                    {d.slice(0, 6).map((b) => (
                      <BuildRow key={b.id} b={b} projectName={names.get(b.projectId)} />
                    ))}
                  </div>
                )}
              </QueryView>
            </Card>
          </section>

          <section>
            <SectionTitle>Recent activity</SectionTitle>
            <Card>
              <QueryView
                query={activity}
                compact
                isEmpty={(d) => d.length === 0}
                empty={<EmptyState compact title="No activity yet">Create a project to get started.</EmptyState>}
              >
                {(d) => (
                  <ol className="divide-y divide-border">
                    {d.map((e) => {
                      const Icon = ACTIVITY_ICON[e.kind];
                      const bad = e.kind.endsWith("failed");
                      const ai = e.kind.startsWith("agent");
                      return (
                        <li key={e.id} className="flex items-start gap-3 px-5 py-3">
                          <span
                            className={cn(
                              "mt-0.5 grid size-7 shrink-0 place-items-center rounded-lg",
                              bad ? "bg-destructive-soft text-destructive" : ai ? "bg-ai-soft text-ai" : "bg-surface-3 text-muted-foreground",
                            )}
                          >
                            <Icon className="size-3.5" aria-hidden />
                          </span>
                          <div className="min-w-0 flex-1">
                            <p className="text-[14px]">{e.message}</p>
                            <p className="text-[13px] text-muted-foreground">
                              <Link href={`/projects/${e.projectId}/ide`} className="hover:text-foreground">
                                {e.projectName}
                              </Link>{" "}
                              · <time dateTime={e.at}>{formatRelative(e.at)}</time>
                            </p>
                          </div>
                        </li>
                      );
                    })}
                  </ol>
                )}
              </QueryView>
            </Card>
          </section>
        </div>

        <aside className="grid min-w-0 grid-cols-[minmax(0,1fr)] content-start gap-6">
          <section>
            <SectionTitle>Agent tasks running</SectionTitle>
            <Card>
              <QueryView
                query={activeTasks}
                compact
                isEmpty={(d) => d.length === 0}
                empty={<EmptyState compact icon={<Bot />} title="No agents running">Ask the assistant in any project to start one.</EmptyState>}
              >
                {(d) => (
                  <ul className="divide-y divide-border">
                    {d.map((t) => (
                      <li key={t.id}>
                        <Link href={`/projects/${t.projectId}/agent?task=${t.id}`} className="block px-5 py-3 transition-colors duration-150 hover:bg-primary-soft">
                          <div className="flex items-center justify-between gap-2">
                            <span className="truncate text-[14px] font-medium">{t.title}</span>
                            <AgentStatusBadge status={t.status} />
                          </div>
                          <p className="mt-0.5 truncate text-[13px] text-muted-foreground">
                            {names.get(t.projectId) ?? t.projectId}
                            {t.currentStep ? ` · ${t.currentStep}` : ""}
                          </p>
                        </Link>
                      </li>
                    ))}
                  </ul>
                )}
              </QueryView>
            </Card>
          </section>

          <section>
            <SectionTitle>
              <Link href="/billing" className="hover:underline">
                Usage this period
              </Link>
            </SectionTitle>
            <Card>
              <CardContent className="grid gap-4">
                {usage.isPending ? (
                  <Skeleton className="h-24" />
                ) : usage.isError ? (
                  <ErrorState error={usage.error} onRetry={() => usage.refetch()} compact />
                ) : (
                  <>
                    <Meter label="AI tokens" used={usage.data.aiTokens.used} limit={usage.data.aiTokens.limit} format={formatNumber} />
                    <Meter label="Storage" used={usage.data.storage.usedBytes} limit={usage.data.storage.limitBytes} format={(n) => formatBytes(n)} />
                    <Meter label="Build minutes" used={usage.data.buildMinutes.used} limit={usage.data.buildMinutes.limit} />
                  </>
                )}
              </CardContent>
            </Card>
          </section>
        </aside>
      </div>
    </PageBody>
  );
}
