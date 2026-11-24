"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";
import type { Build, BuildOutputType, BuildVariant } from "@apppilot/contracts";
import { Bot, Download, Hammer, RotateCw, Square, XCircle } from "lucide-react";
import { toast } from "sonner";
import { PageBody } from "@/components/layout/page";
import { LogViewer } from "@/components/logs/log-viewer";
import { EmptyState, ErrorState, LoadingRows, QueryView } from "@/components/states/states";
import { BuildStatusBadge } from "@/components/status/status-badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogTitle, Segmented, Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/overlays";
import { Badge, Card, Table, TBody, TD, TH, THead, TR } from "@/components/ui/primitives";
import { api } from "@/lib/api/client";
import { errorMessage, isPendingBackend } from "@/lib/api/errors";
import { useArtifacts, useBuild, useBuildActions, useBuilds, useProject } from "@/lib/api/hooks";
import { formatBytes, formatDateTime, formatDuration, formatRelative } from "@/lib/utils";
import { useBuildLog } from "./use-build-log";

function NewBuild({ projectId, disabled }: { projectId: string; disabled?: boolean }) {
  const { start } = useBuildActions(projectId);
  const [type, setType] = useState<BuildOutputType>("apk");
  const [variant, setVariant] = useState<BuildVariant>("debug");
  return (
    <div className="flex flex-wrap items-center gap-2">
      <Segmented<BuildOutputType> aria-label="Output type" value={type} onChange={setType} options={[{ value: "apk", label: "APK" }, { value: "aab", label: "AAB" }]} />
      <Segmented<BuildVariant> aria-label="Variant" value={variant} onChange={setVariant} options={[{ value: "debug", label: "Debug" }, { value: "release", label: "Release" }]} />
      <Button
        disabled={disabled}
        loading={start.isPending}
        onClick={() =>
          start.mutate(
            { projectId, outputType: type, variant },
            {
              onSuccess: (b) => toast.success(`Build #${b.number} started`),
              onError: (e) => toast.error(isPendingBackend(e) ? "Builds aren't available yet — the build service endpoint is pending." : errorMessage(e)),
            },
          )
        }
      >
        <Hammer /> Start build
      </Button>
    </div>
  );
}

function Artifacts({ buildId }: { buildId: string }) {
  const artifacts = useArtifacts(buildId);
  const [busy, setBusy] = useState<string | null>(null);
  const download = async (id: string) => {
    setBusy(id);
    try {
      const { url } = await api.artifacts.download(id);
      window.location.assign(url);
    } catch (e) {
      toast.error(errorMessage(e));
    } finally {
      setBusy(null);
    }
  };
  return (
    <QueryView query={artifacts} compact isEmpty={(d) => d.length === 0} empty={<EmptyState compact title="No artifacts">Only successful builds produce downloadable files.</EmptyState>}>
      {(list) => (
        <ul className="divide-y divide-border rounded-md border border-border">
          {list.map((a) => (
            <li key={a.id} className="flex items-center gap-3 px-3 py-2">
              <Badge tone="outline" className="uppercase">{a.kind.replace("_", " ")}</Badge>
              <span className="min-w-0 flex-1">
                <span className="block truncate font-mono text-[14px]">{a.fileName}</span>
                <span className="block text-[13px] text-muted-foreground">{formatBytes(a.sizeBytes)} · sha256 {a.sha256}</span>
              </span>
              <Button variant="outline" size="sm" loading={busy === a.id} onClick={() => download(a.id)}>
                <Download /> Download
              </Button>
            </li>
          ))}
        </ul>
      )}
    </QueryView>
  );
}

function BuildDetail({ buildId, projectId }: { buildId: string; projectId: string }) {
  const build = useBuild(buildId);
  const { retry, cancel } = useBuildActions(projectId);
  const log = useBuildLog(build.data);

  if (build.isPending) return <LoadingRows rows={8} />;
  if (build.isError) return <ErrorState error={build.error} onRetry={() => build.refetch()} />;
  const b = build.data;

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="grid gap-4 border-b border-border p-5 pr-12">
        <div className="flex flex-wrap items-center gap-2">
          <DialogTitle>Build #{b.number}</DialogTitle>
          <BuildStatusBadge status={b.status} />
          {b.triggeredBy === "agent" ? <Badge tone="ai"><Bot aria-hidden /> Agent</Badge> : null}
        </div>
        <DialogDescription className="sr-only">Build configuration, errors, log and artifacts</DialogDescription>
        <dl className="grid grid-cols-2 gap-x-6 gap-y-2 text-[14px] sm:grid-cols-4">
          {[
            ["Output", `${b.outputType.toUpperCase()} · ${b.variant}`],
            ["Gradle task", <span key="t" className="font-mono text-[13px]">{b.gradleTask}</span>],
            ["Commit", <span key="c" className="font-mono text-[13px]">{b.commitSha ?? "—"}</span>],
            ["Duration", b.status === "running" ? "Running" : formatDuration(b.durationMs)],
            ["Queued", formatDateTime(b.queuedAt)],
            ["Finished", formatDateTime(b.finishedAt)],
          ].map(([k, v]) => (
            <div key={String(k)}>
              <dt className="text-[13px] text-muted-foreground">{k}</dt>
              <dd className="mt-0.5">{v}</dd>
            </div>
          ))}
        </dl>
        <div className="flex gap-2">
          {b.status === "running" || b.status === "queued" ? (
            <Button variant="outline" size="sm" loading={cancel.isPending} onClick={() => cancel.mutate(b.id, { onError: (e) => toast.error(errorMessage(e)) })}>
              <Square /> Cancel build
            </Button>
          ) : (
            <Button variant="outline" size="sm" loading={retry.isPending} onClick={() => retry.mutate(b.id, { onSuccess: (nb) => toast.success(`Build #${nb.number} started`), onError: (e) => toast.error(errorMessage(e)) })}>
              <RotateCw /> Retry build
            </Button>
          )}
        </div>
      </div>
      <Tabs defaultValue={b.errors.length ? "errors" : "log"} className="flex min-h-0 flex-1 flex-col">
        <TabsList className="px-3">
          <TabsTrigger value="errors">Errors {b.errors.length ? <Badge tone="danger">{b.errors.length}</Badge> : null}</TabsTrigger>
          <TabsTrigger value="log">Log</TabsTrigger>
          <TabsTrigger value="artifacts">Artifacts</TabsTrigger>
        </TabsList>
        <TabsContent value="errors" className="min-h-0 flex-1 overflow-auto p-5">
          {b.errorSummary ? <p className="mb-3 text-[14px]"><XCircle className="mr-1.5 inline size-4 text-destructive" aria-hidden />{b.errorSummary}</p> : null}
          {b.errors.length === 0 ? (
            <EmptyState compact title="No errors">This build didn&apos;t report any compiler or Gradle errors.</EmptyState>
          ) : (
            <ul className="grid gap-2">
              {b.errors.map((e, i) => (
                <li key={i} className="rounded-md border border-border p-3">
                  <div className="flex items-center gap-2">
                    <Badge tone={e.severity === "error" ? "danger" : "warning"}>{e.severity}</Badge>
                    {e.task ? <span className="font-mono text-[13px] text-muted-foreground">{e.task}</span> : null}
                  </div>
                  <p className="mt-1.5 text-[14px]">{e.message}</p>
                  {e.path ? (
                    <a href={`/projects/${projectId}/ide?open=${encodeURIComponent(e.path)}&line=${e.line ?? 1}`} className="mt-1 inline-block font-mono text-[13px] text-primary hover:underline">
                      {e.path}:{e.line}:{e.column}
                    </a>
                  ) : null}
                </li>
              ))}
            </ul>
          )}
        </TabsContent>
        <TabsContent value="log" className="flex min-h-0 flex-1 flex-col">
          {log.query.isError ? <ErrorState error={log.query.error} compact /> : <LogViewer lines={log.lines} live={log.live} className="flex-1" />}
        </TabsContent>
        <TabsContent value="artifacts" className="min-h-0 flex-1 overflow-auto p-5">
          <Artifacts buildId={b.id} />
        </TabsContent>
      </Tabs>
    </div>
  );
}

export function BuildCenterScreen({ projectId }: { projectId: string }) {
  const builds = useBuilds(projectId);
  const project = useProject(projectId);
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const selected = params.get("build");
  const open = (id: string | null) => router.replace(id ? `${pathname}?build=${id}` : pathname, { scroll: false });

  return (
    <PageBody>
      {/* The project tabs already name this page; only its action sits here. */}
      <div className="mb-4 flex justify-end">
        <NewBuild projectId={projectId} disabled={project.data?.isApkAnalysis} />
      </div>
      <Card>
        <QueryView
          query={builds}
          loading={<LoadingRows rows={6} />}
          isEmpty={(d) => d.length === 0}
          empty={<EmptyState icon={<Hammer />} title="No builds yet">Start a debug APK build to check the project compiles.</EmptyState>}
        >
          {(list: Build[]) => (
            <Table>
              <THead>
                <TR>
                  <TH>Build</TH>
                  <TH>Status</TH>
                  <TH>Output</TH>
                  <TH className="hidden md:table-cell">Triggered by</TH>
                  <TH className="hidden sm:table-cell">Duration</TH>
                  <TH className="hidden sm:table-cell">Started</TH>
                </TR>
              </THead>
              <TBody>
                {list.map((b) => (
                  <TR key={b.id} data-selected={b.id === selected} className="cursor-pointer" onClick={() => open(b.id)}>
                    <TD>
                      <button className="font-medium hover:underline" onClick={(e) => { e.stopPropagation(); open(b.id); }}>
                        #{b.number}
                      </button>
                      {b.errorSummary ? <p className="max-w-xs truncate text-[13px] text-destructive">{b.errorSummary}</p> : null}
                    </TD>
                    <TD><BuildStatusBadge status={b.status} /></TD>
                    <TD><span className="uppercase">{b.outputType}</span> <span className="text-muted-foreground">· {b.variant}</span></TD>
                    <TD className="hidden md:table-cell">{b.triggeredBy === "agent" ? <Badge tone="ai"><Bot aria-hidden /> Agent</Badge> : <span className="text-muted-foreground">You</span>}</TD>
                    <TD className="hidden tabular-nums text-muted-foreground sm:table-cell">{b.status === "running" ? "—" : formatDuration(b.durationMs)}</TD>
                    <TD className="hidden text-muted-foreground sm:table-cell">{formatRelative(b.startedAt ?? b.queuedAt)}</TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          )}
        </QueryView>
      </Card>

      <Dialog open={!!selected} onOpenChange={(o) => !o && open(null)}>
        <DialogContent side="right" className="max-w-3xl p-0">
          {selected ? <BuildDetail key={selected} buildId={selected} projectId={projectId} /> : null}
        </DialogContent>
      </Dialog>
    </PageBody>
  );
}
