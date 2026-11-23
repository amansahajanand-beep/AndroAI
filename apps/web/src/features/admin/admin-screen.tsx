"use client";

import { useMemo, useState } from "react";
import type { WorkerStatus } from "@apppilot/contracts";
import { Search } from "lucide-react";
import { PageBody, PageHeader, SectionTitle } from "@/components/layout/page";
import { ErrorState, QueryView } from "@/components/states/states";
import { Badge, Card, Input, Skeleton, Table, TBody, TD, TH, THead, TR } from "@/components/ui/primitives";
import { useAdminAudit, useAdminOverview, useAdminUsers, useAdminWorkers } from "@/lib/api/hooks";
import { formatNumber, formatRelative, formatUsd } from "@/lib/utils";

const WORKER_TONE: Record<WorkerStatus["state"], "success" | "info" | "warning" | "danger"> = {
  idle: "success",
  busy: "info",
  draining: "warning",
  offline: "danger",
};

export function AdminScreen() {
  const overview = useAdminOverview();
  const users = useAdminUsers();
  const workers = useAdminWorkers();
  const audit = useAdminAudit();
  const [q, setQ] = useState("");
  const filteredUsers = useMemo(() => {
    const n = q.toLowerCase();
    return users.data?.items.filter((u) => !n || u.email.toLowerCase().includes(n) || u.name.toLowerCase().includes(n)) ?? [];
  }, [users.data, q]);

  const o = overview.data;
  const stats: [string, React.ReactNode][] = o
    ? [
        ["Users", formatNumber(o.users)],
        ["Active in last 7 days", formatNumber(o.activeUsers7d)],
        ["Projects", formatNumber(o.projects)],
        ["Builds today", formatNumber(o.buildsToday)],
        ["Build failure rate (24h)", <span key="f" className={o.buildFailureRate24h > 0.2 ? "text-destructive" : undefined}>{(o.buildFailureRate24h * 100).toFixed(1)}%</span>],
        ["Agent tasks running", formatNumber(o.agentTasksRunning)],
        ["Queue: builds / agent / tests", `${o.queueDepth.builds} / ${o.queueDepth.agent} / ${o.queueDepth.tests}`],
        ["AI cost today", formatUsd(o.aiCostTodayUsd)],
      ]
    : [];

  return (
    <PageBody>
      <PageHeader title="Admin" description="Platform health, worker pools and accounts." />
      {overview.isError ? (
        <ErrorState error={overview.error} onRetry={() => overview.refetch()} />
      ) : (
        <dl className="grid grid-cols-2 gap-px overflow-hidden rounded-xl border border-border bg-border md:grid-cols-4">
          {(o ? stats : Array.from({ length: 8 }, (_, i) => [String(i), null] as [string, null])).map(([k, v]) => (
            <div key={k} className="bg-card px-5 py-3.5">
              {o ? <dt className="text-[13px] text-muted-foreground">{k}</dt> : <Skeleton className="h-3 w-20" />}
              <dd className="mt-1 text-xl font-semibold tabular-nums">{o ? v : <Skeleton className="h-6 w-14" />}</dd>
            </div>
          ))}
        </dl>
      )}

      <div className="mt-6 grid gap-6 lg:grid-cols-[minmax(0,1fr)_360px]">
        <section className="min-w-0">
          <SectionTitle action={
            <div className="relative w-56">
              <Search className="pointer-events-none absolute left-2 top-1/2 size-3.5 -translate-y-1/2 text-subtle-foreground" aria-hidden />
              <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search users" aria-label="Search users" className="h-7 pl-7 text-[13px]" />
            </div>
          }>Users</SectionTitle>
          <Card>
            <QueryView query={users}>
              {() => (
                <Table>
                  <THead><TR><TH>User</TH><TH>Plan</TH><TH className="hidden sm:table-cell">Projects</TH><TH>Status</TH><TH className="hidden md:table-cell">Last active</TH></TR></THead>
                  <TBody>
                    {filteredUsers.map((u) => (
                      <TR key={u.id}>
                        <TD><p className="font-medium">{u.name} {u.role === "admin" ? <Badge tone="primary" className="ml-1">admin</Badge> : null}</p><p className="text-[13px] text-muted-foreground">{u.email}</p></TD>
                        <TD className="capitalize">{u.planId}</TD>
                        <TD className="hidden tabular-nums sm:table-cell">{u.projectCount}</TD>
                        <TD><Badge tone={u.status === "active" ? "success" : "danger"}>{u.status}</Badge></TD>
                        <TD className="hidden text-muted-foreground md:table-cell">{formatRelative(u.lastActiveAt)}</TD>
                      </TR>
                    ))}
                  </TBody>
                </Table>
              )}
            </QueryView>
          </Card>
        </section>
        <div className="grid min-w-0 grid-cols-[minmax(0,1fr)] content-start gap-6">
          <section>
            <SectionTitle>Workers</SectionTitle>
            <Card>
              <QueryView query={workers} compact>
                {(list) => (
                  <ul className="divide-y divide-border">
                    {list.map((w) => (
                      <li key={w.id} className="flex items-center justify-between gap-2 px-5 py-2 text-[14px]">
                        <span><span className="font-mono">{w.id}</span> <span className="text-[13px] text-muted-foreground">{w.pool}</span></span>
                        <span className="flex items-center gap-2">
                          {w.currentJobId ? <span className="font-mono text-[13px] text-muted-foreground">{w.currentJobId}</span> : null}
                          <Badge tone={WORKER_TONE[w.state]} title={`Last heartbeat ${formatRelative(w.lastHeartbeatAt)}`}>{w.state}</Badge>
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
              </QueryView>
            </Card>
          </section>
          <section>
            <SectionTitle>Audit log</SectionTitle>
            <Card>
              <QueryView query={audit} compact isEmpty={(d) => d.length === 0}>
                {(list) => (
                  <ul className="divide-y divide-border">
                    {list.map((a) => (
                      <li key={a.id} className="px-5 py-2 text-[14px]">
                        <p><span className="font-mono text-[13px]">{a.action}</span> → {a.target}</p>
                        <p className="text-[13px] text-muted-foreground">{a.actorEmail} · {formatRelative(a.at)}</p>
                      </li>
                    ))}
                  </ul>
                )}
              </QueryView>
            </Card>
          </section>
        </div>
      </div>
    </PageBody>
  );
}
