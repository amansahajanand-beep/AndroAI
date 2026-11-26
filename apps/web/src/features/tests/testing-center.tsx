"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useMemo } from "react";
import type { TestCase, TestJob, TestJobKind, ValidationStatus } from "@apppilot/contracts";
import { Bot, HelpCircle, Play, Smartphone, TestTube2 } from "lucide-react";
import { toast } from "sonner";
import { PageBody } from "@/components/layout/page";
import { LogViewer } from "@/components/logs/log-viewer";
import { EmptyState, LoadingRows, QueryView } from "@/components/states/states";
import { VALIDATION_STATUS, ValidationBadge } from "@/components/status/status-badge";
import { Button } from "@/components/ui/button";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger, Popover, PopoverContent, PopoverTrigger, Tabs, TabsContent, TabsList, TabsTrigger, Tooltip } from "@/components/ui/overlays";
import { Badge, Card } from "@/components/ui/primitives";
import { errorMessage, isPendingBackend } from "@/lib/api/errors";
import { useScreenshots, useStartTests, useTestCases, useTestJobs, useTestLogs } from "@/lib/api/hooks";
import { cn, formatDuration, formatRelative } from "@/lib/utils";

const KIND_LABEL: Record<TestJobKind, string> = { unit: "Unit tests", instrumentation: "Instrumentation tests", emulator: "Emulator run" };
const ORDER: ValidationStatus[] = ["failed", "blocked", "unverified", "passed", "skipped"];

function SummaryCounts({ job }: { job: TestJob }) {
  return (
    <span className="flex flex-wrap gap-x-2.5 gap-y-1 text-[13px]">
      {ORDER.filter((s) => job.summary[s] > 0).map((s) => {
        const Icon = VALIDATION_STATUS[s].icon;
        return (
          <Tooltip key={s} content={VALIDATION_STATUS[s].description}>
            <span className={cn("inline-flex items-center gap-1 tabular-nums", { failed: "text-destructive", blocked: "text-warning", unverified: "text-info", passed: "text-success", skipped: "text-muted-foreground" }[s])}>
              <Icon className="size-3.5" aria-hidden />
              {job.summary[s]} {VALIDATION_STATUS[s].label.toLowerCase()}
            </span>
          </Tooltip>
        );
      })}
    </span>
  );
}

function CaseList({ cases }: { cases: TestCase[] }) {
  const suites = useMemo(() => {
    const m = new Map<string, TestCase[]>();
    [...cases]
      .sort((a, b) => ORDER.indexOf(a.status) - ORDER.indexOf(b.status))
      .forEach((c) => m.set(c.suite, [...(m.get(c.suite) ?? []), c]));
    return [...m];
  }, [cases]);
  return (
    <div className="grid gap-4">
      {suites.map(([suite, list]) => (
        <section key={suite}>
          <h3 className="mb-1.5 font-mono text-[13px] text-muted-foreground">{suite}</h3>
          <ul className="divide-y divide-border rounded-md border border-border">
            {list.map((c) => (
              <li key={c.id} className="px-3 py-2">
                <details open={c.status === "failed"} className="group">
                  <summary className={cn("flex cursor-pointer list-none items-center gap-2", !c.failureMessage && "cursor-default")}>
                    <ValidationBadge status={c.status} />
                    <span className="min-w-0 flex-1 truncate font-mono text-[14px]">{c.name}</span>
                    <span className="text-[13px] tabular-nums text-muted-foreground">{formatDuration(c.durationMs)}</span>
                  </summary>
                  {c.failureMessage ? (
                    <div className="mt-2 grid gap-2">
                      <p className="text-[14px]">{c.failureMessage}</p>
                      {c.stackTrace ? <pre className="overflow-x-auto rounded-sm bg-background p-2 font-mono text-[12px] text-muted-foreground">{c.stackTrace}</pre> : null}
                    </div>
                  ) : null}
                </details>
              </li>
            ))}
          </ul>
        </section>
      ))}
    </div>
  );
}

function JobDetail({ job }: { job: TestJob }) {
  const cases = useTestCases(job.id);
  const shots = useScreenshots(job.id);
  const logs = useTestLogs(job.id);
  return (
    <div className="flex min-h-0 flex-col">
      <div className="grid gap-2 border-b border-border p-5">
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="text-base font-semibold">{KIND_LABEL[job.kind]}</h2>
          <ValidationBadge status={job.result} />
          {job.triggeredBy === "agent" ? <Badge tone="ai"><Bot aria-hidden /> Agent</Badge> : null}
        </div>
        <p className="text-[13px] text-muted-foreground">
          {job.device ? `${job.device.name} · API ${job.device.apiLevel} · ${job.device.abi} · ` : ""}
          {formatDuration(job.durationMs)} · {formatRelative(job.finishedAt ?? job.startedAt)}
        </p>
        <SummaryCounts job={job} />
      </div>
      <Tabs defaultValue="results">
        <TabsList className="px-3">
          <TabsTrigger value="results">Results</TabsTrigger>
          {job.kind !== "unit" ? <TabsTrigger value="screenshots">Screenshots</TabsTrigger> : null}
          <TabsTrigger value="logs">Logs</TabsTrigger>
        </TabsList>
        <TabsContent value="results" className="p-5">
          <QueryView query={cases} isEmpty={(d) => d.length === 0} empty={<EmptyState compact title="No test cases reported" />}>
            {(d) => <CaseList cases={d} />}
          </QueryView>
        </TabsContent>
        <TabsContent value="screenshots" className="p-5">
          <QueryView query={shots} isEmpty={(d) => d.length === 0} empty={<EmptyState compact icon={<Smartphone />} title="No screenshots">Screenshots appear when an emulator run captures the screen.</EmptyState>}>
            {(d) => (
              <ul className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4">
                {d.map((s) => (
                  <li key={s.id}>
                    <a href={s.url} target="_blank" rel="noreferrer" className="block overflow-hidden rounded-md border border-border bg-background transition-colors duration-200 hover:border-border-strong">
                      {/* eslint-disable-next-line @next/next/no-img-element -- signed URLs from artifact storage */}
                      <img src={s.url} alt={s.caption} className="aspect-[9/19] w-full object-cover" loading="lazy" />
                    </a>
                    <p className="mt-1.5 truncate text-[13px] text-muted-foreground">{s.caption}</p>
                  </li>
                ))}
              </ul>
            )}
          </QueryView>
        </TabsContent>
        <TabsContent value="logs" className="h-96">
          <QueryView query={logs} compact>
            {(text) => <LogViewer text={text} className="h-96" />}
          </QueryView>
        </TabsContent>
      </Tabs>
    </div>
  );
}

export function TestingCenterScreen({ projectId }: { projectId: string }) {
  const jobs = useTestJobs(projectId);
  const start = useStartTests(projectId);
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const selectedId = params.get("job") ?? jobs.data?.[0]?.id ?? null;
  const selected = jobs.data?.find((j) => j.id === selectedId);

  const run = (kind: TestJobKind) =>
    start.mutate(
      { projectId, kind },
      {
        onSuccess: () => toast.success(`${KIND_LABEL[kind]} queued`),
        onError: (e) => toast.error(isPendingBackend(e) ? "Test runs aren't available yet — the test service endpoint is pending." : errorMessage(e)),
      },
    );

  return (
    <PageBody>
      {/* The project tabs already name this page; the status guide and the action sit here. */}
      <div className="mb-4 flex items-center justify-between gap-2">
        <Popover>
          <PopoverTrigger asChild>
            <Button variant="subtle" size="sm">
              <HelpCircle /> Status guide
            </Button>
          </PopoverTrigger>
          <PopoverContent className="w-80">
            <p className="mb-2 text-[13px] font-semibold">Results use five statuses</p>
            <ul className="grid gap-2 text-[13px] text-muted-foreground">
              {(Object.keys(VALIDATION_STATUS) as ValidationStatus[]).map((st) => (
                <li key={st} className="flex items-start gap-2">
                  <ValidationBadge status={st} className="shrink-0" />
                  <span>{VALIDATION_STATUS[st].description}</span>
                </li>
              ))}
            </ul>
          </PopoverContent>
        </Popover>
        <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button loading={start.isPending}>
                <Play /> Run tests
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              {(Object.keys(KIND_LABEL) as TestJobKind[]).map((k) => (
                <DropdownMenuItem key={k} onSelect={() => run(k)}>
                  {KIND_LABEL[k]}
                </DropdownMenuItem>
              ))}
            </DropdownMenuContent>
        </DropdownMenu>
      </div>
      <QueryView
        query={jobs}
        loading={<LoadingRows rows={5} />}
        isEmpty={(d) => d.length === 0}
        empty={
          <Card>
            <EmptyState
              icon={<TestTube2 />}
              title="No test runs yet"
              action={
                <Button size="sm" loading={start.isPending} onClick={() => run("unit")}>
                  <Play /> Run unit tests
                </Button>
              }
            >
              Run unit tests to check the project&apos;s logic, or an emulator run to check screens.
            </EmptyState>
          </Card>
        }
      >
        {(list) => (
          <div className="grid gap-4 lg:grid-cols-[320px_minmax(0,1fr)]">
            <Card className="h-fit overflow-hidden">
              <ul className="divide-y divide-border" role="listbox" aria-label="Test jobs">
                {list.map((j) => (
                  <li key={j.id} role="option" aria-selected={j.id === selectedId}>
                    <button
                      onClick={() => router.replace(`${pathname}?job=${j.id}`, { scroll: false })}
                      className={cn("grid w-full gap-1 px-3 py-2.5 text-left hover:bg-surface-2", j.id === selectedId && "bg-surface-2")}
                    >
                      <span className="flex items-center justify-between gap-2">
                        <span className="text-[14px] font-medium">{KIND_LABEL[j.kind]}</span>
                        <ValidationBadge status={j.result} />
                      </span>
                      <span className="text-[13px] text-muted-foreground">
                        {j.state === "finished" ? formatRelative(j.finishedAt) : j.state}
                        {j.device ? ` · ${j.device.name}` : ""}
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            </Card>
            <Card className="min-w-0">{selected ? <JobDetail key={selected.id} job={selected} /> : <EmptyState title="Select a test run" />}</Card>
          </div>
        )}
      </QueryView>
    </PageBody>
  );
}
