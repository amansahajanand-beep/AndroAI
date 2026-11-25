"use client";

import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useMemo, useState } from "react";
import { AGENT_TASK_STATUSES, type AgentTask, type AgentTaskStatus } from "@apppilot/contracts";
import { Bot, Code2, FileSearch, FilePen, OctagonPause, Radio, Square, XCircle } from "lucide-react";
import { toast } from "sonner";
import { PageBody } from "@/components/layout/page";
import { EmptyState, ErrorState, LoadingRows, QueryView } from "@/components/states/states";
import { AGENT_STATUS, AgentStatusBadge, isAgentActive } from "@/components/status/status-badge";
import { Button } from "@/components/ui/button";
import { ConfirmDialog, Select } from "@/components/ui/overlays";
import { Alert, Card, Progress } from "@/components/ui/primitives";
import { errorMessage } from "@/lib/api/errors";
import { useAgentTask, useAgentTasks, useCancelTask, useTimeline } from "@/lib/api/hooks";
import { cn, formatDateTime, formatDuration, formatNumber, formatRelative, formatUsd } from "@/lib/utils";
import { useNow } from "@/hooks/use-now";
import { useTaskStream } from "./use-task-stream";

type Filter = "all" | "active" | AgentTaskStatus;

function TaskList({ tasks, selected, onSelect }: { tasks: AgentTask[]; selected: string | null; onSelect: (id: string) => void }) {
  return (
    <ul className="divide-y divide-border" role="listbox" aria-label="Agent tasks">
      {tasks.map((t) => (
        <li key={t.id} role="option" aria-selected={t.id === selected}>
          <button
            onClick={() => onSelect(t.id)}
            className={cn("block w-full px-3 py-2.5 text-left hover:bg-surface-2", t.id === selected && "bg-surface-2 shadow-[inset_2px_0_0_var(--color-ai)]")}
          >
            <span className="flex items-center justify-between gap-2">
              <span className="truncate text-[14px] font-medium">{t.title}</span>
              <AgentStatusBadge status={t.status} />
            </span>
            <span className="mt-0.5 block truncate text-[13px] text-muted-foreground">
              {t.intent} · {formatRelative(t.createdAt)}
            </span>
          </button>
        </li>
      ))}
    </ul>
  );
}

function FileList({ icon: Icon, title, files, tone }: { icon: typeof FileSearch; title: string; files: string[]; tone: string }) {
  return (
    <section>
      <h3 className="mb-1.5 flex items-center gap-1.5 text-[13px] font-medium text-muted-foreground">
        <Icon className={cn("size-3.5", tone)} aria-hidden /> {title} ({files.length})
      </h3>
      {files.length ? (
        <ul className="grid gap-0.5">
          {files.map((f) => (
            <li key={f} className="truncate font-mono text-[13px]" title={f}>
              {f}
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-[13px] text-subtle-foreground">None right now</p>
      )}
    </section>
  );
}

function TaskDetail({ taskId, projectId }: { taskId: string; projectId: string }) {
  const task = useAgentTask(taskId);
  const timeline = useTimeline(taskId);
  const cancel = useCancelTask();
  const [confirm, setConfirm] = useState(false);
  const stream = useTaskStream(task.data);
  const now = useNow(1000, !!task.data && isAgentActive(task.data.status));

  if (task.isPending) return <LoadingRows rows={6} />;
  if (task.isError) return <ErrorState error={task.error} onRetry={() => task.refetch()} />;
  const t = task.data;
  const active = isAgentActive(t.status);
  const meta = AGENT_STATUS[t.status];
  const elapsed = t.startedAt ? (t.finishedAt ? new Date(t.finishedAt).getTime() : now) - new Date(t.startedAt).getTime() : null;

  return (
    <div className="grid gap-5 p-5">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <h2 className="truncate text-base font-semibold">{t.title}</h2>
            <AgentStatusBadge status={t.status} />
          </div>
          {t.description ? <p className="mt-1 text-[14px] text-muted-foreground">{t.description}</p> : null}
        </div>
        <div className="flex items-center gap-2">
          {active ? (
            <span className="flex items-center gap-1 text-[13px] text-muted-foreground" aria-live="polite">
              <Radio className={cn("size-3.5", stream === "open" ? "text-success" : "text-warning")} aria-hidden />
              {stream === "open" ? "Live" : stream === "reconnecting" ? "Reconnecting…" : "Connecting…"}
            </span>
          ) : null}
          <Button asChild variant="outline" size="sm">
            <Link href={`/projects/${projectId}/ide`}>
              <Code2 /> Open IDE
            </Link>
          </Button>
          {active ? (
            <Button variant="outline" size="sm" onClick={() => setConfirm(true)}>
              <Square /> Cancel task
            </Button>
          ) : null}
        </div>
      </header>

      {t.status === "blocked" && t.blockedReason ? (
        <Alert tone="warning"><OctagonPause /><span><strong className="font-medium">Blocked: </strong>{t.blockedReason}</span></Alert>
      ) : null}
      {t.status === "failed" && t.errorMessage ? (
        <Alert tone="danger"><XCircle /><span>{t.errorMessage}</span></Alert>
      ) : null}

      <dl className="grid grid-cols-2 gap-x-6 gap-y-3 rounded-lg border border-border bg-card px-4 py-3 text-[14px] sm:grid-cols-4">
        {[
          ["Current step", t.currentStep ?? (active ? meta.description : "—")],
          ["Repair iterations", `${t.repairIterations} of ${t.maxRepairIterations}`],
          ["Tokens", `${formatNumber(t.tokenUsage.inputTokens)} in · ${formatNumber(t.tokenUsage.outputTokens)} out`],
          ["Recorded cost", formatUsd(t.recordedCostUsd)],
        ].map(([k, v]) => (
          <div key={k} className="min-w-0">
            <dt className="text-[12.5px] text-muted-foreground">{k}</dt>
            <dd className="mt-0.5 truncate" title={String(v)}>{v}</dd>
          </div>
        ))}
      </dl>

      {t.buildProgress ? (
        <section className="grid gap-1.5">
          <div className="flex items-center justify-between text-[13px]">
            <span className="font-mono text-muted-foreground">{t.buildProgress.phase}</span>
            <span className="tabular-nums">{t.buildProgress.percent}%</span>
          </div>
          <Progress value={t.buildProgress.percent} label="Build progress" />
        </section>
      ) : null}

      <div className="grid gap-5 md:grid-cols-[minmax(0,1fr)_260px]">
        <section>
          <h3 className="mb-3 text-[14px] font-semibold">Execution timeline</h3>
          <QueryView query={timeline} compact isEmpty={(d) => d.length === 0} empty={<EmptyState compact title="No steps yet" />}>
            {(events) => (
              <ol className="relative grid gap-4 border-l border-border pl-5">
                {events.map((e, i) => {
                  const m = AGENT_STATUS[e.status];
                  const last = i === events.length - 1;
                  return (
                    <li key={e.id} className="relative">
                      <span
                        className={cn(
                          "absolute -left-[27px] top-0.5 flex size-[13px] items-center justify-center rounded-full border-2 bg-background",
                          last && active ? "border-ai" : m.tone === "danger" ? "border-destructive" : m.tone === "warning" ? "border-warning" : m.tone === "success" ? "border-success" : "border-border-strong",
                        )}
                        aria-hidden
                      >
                        {last && active ? <span className="size-1.5 animate-pulse rounded-full bg-ai" /> : null}
                      </span>
                      <div className="flex flex-wrap items-baseline gap-x-2">
                        <span className="text-[14px] font-medium">{e.title}</span>
                        <span className="text-[13px] text-muted-foreground">{m.label} · <time dateTime={e.at} title={formatDateTime(e.at)}>{formatRelative(e.at)}</time></span>
                      </div>
                      {e.detail ? <p className="mt-0.5 text-[13px] text-muted-foreground">{e.detail}</p> : null}
                      {e.files?.length ? <p className="mt-1 truncate font-mono text-[12px] text-subtle-foreground">{e.files.join(", ")}</p> : null}
                    </li>
                  );
                })}
              </ol>
            )}
          </QueryView>
        </section>
        <aside className="grid min-w-0 grid-cols-[minmax(0,1fr)] content-start gap-4">
          <FileList icon={FileSearch} title="Analyzing" files={t.filesAnalyzing} tone="text-info" />
          <FileList icon={FilePen} title="Modifying" files={t.filesModifying} tone="text-ai" />
          <dl className="grid gap-1 text-[13px] text-muted-foreground">
            <div className="flex justify-between"><dt>Started</dt><dd>{formatDateTime(t.startedAt)}</dd></div>
            <div className="flex justify-between"><dt>{t.finishedAt ? "Took" : "Running for"}</dt><dd>{formatDuration(elapsed)}</dd></div>
          </dl>
        </aside>
      </div>

      <ConfirmDialog
        open={confirm}
        onOpenChange={setConfirm}
        title="Cancel this task?"
        description="The agent stops after its current step. Changes it already proposed stay available for review; nothing is applied without your approval."
        confirmLabel="Cancel task"
        destructive
        loading={cancel.isPending}
        onConfirm={() =>
          cancel.mutate(t.id, {
            onSuccess: () => {
              setConfirm(false);
              toast.success("Task cancelled");
            },
            onError: (e) => toast.error(errorMessage(e)),
          })
        }
      />
    </div>
  );
}

export function AgentScreen({ projectId }: { projectId: string }) {
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const [filter, setFilter] = useState<Filter>("all");
  const tasks = useAgentTasks({ projectId });

  const visible = useMemo(() => {
    const list = tasks.data ?? [];
    if (filter === "all") return list;
    if (filter === "active") return list.filter((t) => isAgentActive(t.status));
    return list.filter((t) => t.status === filter);
  }, [tasks.data, filter]);

  const selected = params.get("task") ?? visible.find((t) => isAgentActive(t.status))?.id ?? visible[0]?.id ?? null;
  const select = (id: string) => router.replace(`${pathname}?task=${id}`, { scroll: false });

  return (
    <PageBody>
      <div className="grid gap-4 lg:grid-cols-[320px_minmax(0,1fr)]">
        <Card className="flex max-h-[calc(100dvh-14rem)] flex-col overflow-hidden lg:sticky lg:top-4">
          <div className="flex items-center gap-2 border-b border-border p-2">
            <Select<Filter>
              aria-label="Filter tasks"
              value={filter}
              onValueChange={setFilter}
              options={[
                { value: "all", label: "All tasks" },
                { value: "active", label: "Active" },
                ...AGENT_TASK_STATUSES.map((s) => ({ value: s, label: AGENT_STATUS[s].label })),
              ]}
            />
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto">
            <QueryView
              query={tasks}
              compact
              isEmpty={() => visible.length === 0}
              empty={<EmptyState compact icon={<Bot />} title={filter === "all" ? "No agent tasks yet" : "No tasks with this status"}>{filter === "all" ? "Ask the assistant in the IDE to plan or change code." : null}</EmptyState>}
            >
              {() => <TaskList tasks={visible} selected={selected} onSelect={select} />}
            </QueryView>
          </div>
        </Card>
        <Card className="min-h-80">
          {selected ? (
            <TaskDetail key={selected} taskId={selected} projectId={projectId} />
          ) : tasks.isPending ? (
            <LoadingRows rows={6} />
          ) : (
            <EmptyState icon={<Bot />} title="Select a task">Pick a task on the left to see its timeline.</EmptyState>
          )}
        </Card>
      </div>
    </PageBody>
  );
}
