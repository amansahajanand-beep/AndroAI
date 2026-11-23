"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import type { Diagnostic } from "@apppilot/contracts";
import { AlertCircle, AlertTriangle, ChevronDown, GitCommitHorizontal, Hammer, Info, Smartphone, Sparkles, SquareTerminal, TestTube2 } from "lucide-react";
import { toast } from "sonner";
import { LogViewer } from "@/components/logs/log-viewer";
import { EmptyState, ErrorState, LoadingRows, QueryView } from "@/components/states/states";
import { BuildStatusBadge, ValidationBadge } from "@/components/status/status-badge";
import { Button } from "@/components/ui/button";
import { Tooltip } from "@/components/ui/overlays";
import { Badge } from "@/components/ui/primitives";
import { errorMessage, isPendingBackend } from "@/lib/api/errors";
import { useBuildActions, useBuilds, useDiagnostics, useGitLog, useTestJobs } from "@/lib/api/hooks";
import { cn, formatDuration, formatRelative } from "@/lib/utils";
import { type BottomTab, useIdeStore } from "@/stores/ide-store";
import { useBuildLog } from "../builds/use-build-log";
import { MOD } from "./shortcuts";
import { TerminalView } from "./terminal-view";

const SEVERITY = {
  error: { icon: AlertCircle, className: "text-destructive" },
  warning: { icon: AlertTriangle, className: "text-warning" },
  info: { icon: Info, className: "text-info" },
};

function Problems({ projectId }: { projectId: string }) {
  const diags = useDiagnostics(projectId);
  const openFile = useIdeStore((s) => s.openFile);
  const grouped = useMemo(() => {
    const m = new Map<string, Diagnostic[]>();
    (diags.data ?? []).forEach((d) => m.set(d.path, [...(m.get(d.path) ?? []), d]));
    return [...m];
  }, [diags.data]);
  return (
    <QueryView query={diags} compact isEmpty={(d) => d.length === 0} empty={<EmptyState compact title="No problems">Problems from the last build and lint run show up here.</EmptyState>}>
      {() => (
        <ul className="py-1 text-[14px]">
          {grouped.map(([path, list]) => (
            <li key={path}>
              <p className="truncate px-3 py-1 font-mono text-[13px] text-muted-foreground">{path}</p>
              <ul>
                {list.map((d, i) => {
                  const S = SEVERITY[d.severity];
                  return (
                    <li key={i}>
                      <button className="flex w-full items-start gap-2 px-3 py-1 pl-6 text-left hover:bg-surface-2" onClick={() => openFile(projectId, d.path, { line: d.line, column: d.column })}>
                        <S.icon className={cn("mt-0.5 size-3.5 shrink-0", S.className)} aria-label={d.severity} />
                        <span className="flex-1">{d.message}</span>
                        <span className="shrink-0 font-mono text-[12px] text-subtle-foreground">{d.source} · {d.line}:{d.column}</span>
                      </button>
                    </li>
                  );
                })}
              </ul>
            </li>
          ))}
        </ul>
      )}
    </QueryView>
  );
}

function BuildOutput({ projectId, readOnly }: { projectId: string; readOnly?: boolean }) {
  const builds = useBuilds(projectId);
  const { start } = useBuildActions(projectId);
  const latest = builds.data?.[0];
  const log = useBuildLog(latest);
  if (builds.isPending) return <LoadingRows rows={3} />;
  if (builds.isError) return <ErrorState error={builds.error} compact onRetry={() => builds.refetch()} />;
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex h-8 shrink-0 items-center gap-2 border-b border-border px-3 text-[13px]">
        {latest ? (
          <>
            <Link href={`/projects/${projectId}/builds?build=${latest.id}`} className="font-medium hover:underline">Build #{latest.number}</Link>
            <BuildStatusBadge status={latest.status} />
            <span className="font-mono text-muted-foreground">{latest.gradleTask}</span>
            {latest.triggeredBy === "agent" ? <Badge tone="ai"><Sparkles aria-hidden /> Agent</Badge> : null}
            <span className="text-muted-foreground">{latest.status === "running" ? "" : formatDuration(latest.durationMs)}</span>
          </>
        ) : (
          <span className="text-muted-foreground">No builds yet</span>
        )}
        {!readOnly ? (
          <Button
            size="sm"
            variant="outline"
            className="ml-auto h-6 text-[13px]"
            loading={start.isPending}
            onClick={() => start.mutate({ projectId, outputType: "apk", variant: "debug" }, { onError: (e) => toast.error(isPendingBackend(e) ? "Builds aren't available yet — the build endpoint is pending." : errorMessage(e)) })}
          >
            <Hammer /> Run debug build
          </Button>
        ) : null}
      </div>
      {latest ? <LogViewer lines={log.lines} live={log.live} className="min-h-0 flex-1" /> : <EmptyState compact title="Run a build to see Gradle output" />}
    </div>
  );
}

function Tests({ projectId }: { projectId: string }) {
  const jobs = useTestJobs(projectId);
  return (
    <QueryView query={jobs} compact isEmpty={(d) => d.length === 0} empty={<EmptyState compact title="No test runs yet" />}>
      {(list) => (
        <ul className="divide-y divide-border text-[14px]">
          {list.slice(0, 8).map((j) => (
            <li key={j.id}>
              <Link href={`/projects/${projectId}/tests?job=${j.id}`} className="flex items-center gap-3 px-3 py-1.5 hover:bg-surface-2">
                <ValidationBadge status={j.result} />
                <span className="w-40 shrink-0 capitalize">{j.kind} tests</span>
                <span className="flex-1 truncate text-[13px] text-muted-foreground">
                  {j.summary.passed} passed · {j.summary.failed} failed · {j.summary.blocked} blocked · {j.summary.unverified} unverified · {j.summary.skipped} skipped
                </span>
                <span className="text-[13px] text-muted-foreground">{formatRelative(j.finishedAt ?? j.startedAt)}</span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </QueryView>
  );
}

function Git({ projectId }: { projectId: string }) {
  const log = useGitLog(projectId);
  return (
    <QueryView query={log} compact isEmpty={(d) => d.length === 0} empty={<EmptyState compact title="No commits yet" />}>
      {(list) => (
        <ul className="divide-y divide-border text-[14px]">
          {list.map((c) => (
            <li key={c.sha} className="flex items-center gap-3 px-3 py-1.5">
              <GitCommitHorizontal className="size-3.5 shrink-0 text-subtle-foreground" aria-hidden />
              <span className="font-mono text-[13px] text-muted-foreground">{c.sha.slice(0, 7)}</span>
              <span className="min-w-0 flex-1 truncate">{c.message}</span>
              {c.aiTaskId ? <Badge tone="ai"><Sparkles aria-hidden /> Agent</Badge> : null}
              <span className="hidden text-[13px] text-muted-foreground sm:inline">{c.author}</span>
              <span className="text-[13px] text-muted-foreground">{formatRelative(c.authoredAt)}</span>
            </li>
          ))}
        </ul>
      )}
    </QueryView>
  );
}

function Preview({ projectId }: { projectId: string }) {
  return (
    <EmptyState compact icon={<Smartphone />} title="Live preview isn't available yet">
      Streaming a running emulator needs a backend service that doesn&apos;t have a contract yet. Meanwhile, emulator test runs
      capture screenshots in the{" "}
      <Link href={`/projects/${projectId}/tests`} className="text-primary hover:underline">Testing center</Link>.
    </EmptyState>
  );
}

export function BottomPanel({ projectId, readOnly }: { projectId: string; readOnly?: boolean }) {
  const tab = useIdeStore((s) => s.layout.bottomTab);
  const setTab = useIdeStore((s) => s.setBottomTab);
  const toggle = useIdeStore((s) => s.togglePanel);
  const diags = useDiagnostics(projectId);
  // Mount the terminal on first visit and keep it alive across tab switches.
  const [terminalMounted, setTerminalMounted] = useState(tab === "terminal");
  const errorCount = diags.data?.filter((d) => d.severity === "error").length ?? 0;
  const warnCount = diags.data?.filter((d) => d.severity === "warning").length ?? 0;

  const TABS: { id: BottomTab; label: string; icon: typeof Hammer; badge?: React.ReactNode }[] = [
    { id: "terminal", label: "Terminal", icon: SquareTerminal },
    { id: "build", label: "Build output", icon: Hammer },
    {
      id: "problems",
      label: "Problems",
      icon: AlertCircle,
      badge: errorCount + warnCount ? <Badge tone={errorCount ? "danger" : "warning"} className="px-1">{errorCount + warnCount}</Badge> : null,
    },
    { id: "tests", label: "Test results", icon: TestTube2 },
    { id: "git", label: "Git history", icon: GitCommitHorizontal },
    { id: "preview", label: "Preview", icon: Smartphone },
  ];

  return (
    <div className="flex h-full min-h-0 flex-col bg-surface">
      <div className="flex h-8 shrink-0 items-center border-b border-border pr-1">
        <div role="tablist" aria-label="Panels" className="flex h-full min-w-0 flex-1 overflow-x-auto">
          {TABS.map((t) => (
            <button
              key={t.id}
              role="tab"
              aria-selected={tab === t.id}
              onClick={() => {
                setTab(t.id);
                if (t.id === "terminal") setTerminalMounted(true);
              }}
              className={cn(
                "flex shrink-0 items-center gap-1.5 border-b-2 px-3 text-[13px]",
                tab === t.id ? "border-primary text-foreground" : "border-transparent text-muted-foreground hover:text-foreground",
              )}
            >
              <t.icon className="size-3.5" aria-hidden />
              {t.label}
              {t.badge}
            </button>
          ))}
        </div>
        <Tooltip content="Hide panel" shortcut={`${MOD}+J`}>
          <Button variant="subtle" size="icon-xs" aria-label="Hide bottom panel" onClick={() => toggle("bottom", false)}>
            <ChevronDown />
          </Button>
        </Tooltip>
      </div>
      <div className="min-h-0 flex-1 overflow-auto" role="tabpanel">
        {terminalMounted || tab === "terminal" ? (
          <div className={cn("h-full", tab !== "terminal" && "hidden")}>
            <TerminalView projectId={projectId} />
          </div>
        ) : null}
        {tab === "build" ? <BuildOutput projectId={projectId} readOnly={readOnly} /> : null}
        {tab === "problems" ? (diags.isError ? <ErrorState error={diags.error} compact /> : <Problems projectId={projectId} />) : null}
        {tab === "tests" ? <Tests projectId={projectId} /> : null}
        {tab === "git" ? <Git projectId={projectId} /> : null}
        {tab === "preview" ? <Preview projectId={projectId} /> : null}
      </div>
    </div>
  );
}
