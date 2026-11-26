"use client";

import { useId, useState } from "react";
import type { UsageDailyPoint } from "@apppilot/contracts";
import { Check, ExternalLink } from "lucide-react";
import { toast } from "sonner";
import { Meter, PageBody, PageHeader, SectionTitle } from "@/components/layout/page";
import { EmptyState, ErrorState, QueryView } from "@/components/states/states";
import { Button } from "@/components/ui/button";
import { Segmented } from "@/components/ui/overlays";
import { Badge, Card, CardContent, Skeleton, Table, TBody, TD, TH, THead, TR } from "@/components/ui/primitives";
import { api } from "@/lib/api/client";
import { errorMessage } from "@/lib/api/errors";
import { useInvoices, usePlans, useSubscription, useUsage, useUsageDaily } from "@/lib/api/hooks";
import { cn, formatBytes, formatDateTime, formatNumber, formatUsd } from "@/lib/utils";

type Metric = "aiTokens" | "buildMinutes" | "aiCostUsd";
const METRIC_LABEL: Record<Metric, string> = { aiTokens: "AI tokens", buildMinutes: "Build minutes", aiCostUsd: "AI cost" };

/** Smooth monotone cubic path through the points (never overshoots the data). */
function smoothPath(pts: [number, number][]): string {
  const n = pts.length;
  const first = pts[0];
  if (!first) return "";
  if (n === 1) return `M${first[0]},${first[1]}`;
  const slope = (i: number) => {
    const [x0, y0] = pts[i]!;
    const [x1, y1] = pts[i + 1]!;
    return (y1 - y0) / (x1 - x0);
  };
  const tangent = (i: number) => {
    if (i === 0) return slope(0);
    if (i === n - 1) return slope(n - 2);
    const a = slope(i - 1);
    const b = slope(i);
    return a * b <= 0 ? 0 : (2 * a * b) / (a + b);
  };
  let d = `M${first[0]},${first[1]}`;
  for (let i = 0; i < n - 1; i++) {
    const [x0, y0] = pts[i]!;
    const [x1, y1] = pts[i + 1]!;
    const dx = (x1 - x0) / 3;
    d += ` C${x0 + dx},${y0 + tangent(i) * dx} ${x1 - dx},${y1 - tangent(i + 1) * dx} ${x1},${y1}`;
  }
  return d;
}

function UsageChart({ data }: { data: UsageDailyPoint[] }) {
  const [metric, setMetric] = useState<Metric>("aiTokens");
  const gradientId = `usage-fill-${useId().replace(/:/g, "")}`;
  const max = Math.max(1, ...data.map((d) => d[metric]));
  // Plot area: 4% padding top, 2% bottom, so the line and hover dot are never clipped.
  const heightPct = (v: number) => 2 + (v / max) * 94;
  const points: [number, number][] = data.map((d, i) => [((i + 0.5) / data.length) * 100, 100 - heightPct(d[metric])]);
  const line = smoothPath(points);
  const firstX = points[0]?.[0] ?? 0;
  const lastX = points[points.length - 1]?.[0] ?? 100;
  const fmt = (n: number) => (metric === "aiCostUsd" ? formatUsd(n) : formatNumber(n));
  const total = data.reduce((s, d) => s + d[metric], 0);
  return (
    <div className="grid h-full grid-rows-[auto_1fr_auto] gap-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-[14px]">
          <span className="font-semibold tabular-nums">{fmt(metric === "aiCostUsd" ? +total.toFixed(2) : total)}</span>{" "}
          <span className="text-muted-foreground">in the last {data.length} days</span>
        </p>
        <Segmented<Metric> aria-label="Metric" value={metric} onChange={setMetric} options={(Object.keys(METRIC_LABEL) as Metric[]).map((m) => ({ value: m, label: METRIC_LABEL[m] }))} />
      </div>
      <div className="relative min-h-[10rem]" role="img" aria-label={`${METRIC_LABEL[metric]} per day, peak ${fmt(max)}`}>
        <svg className="absolute inset-0 size-full" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden>
          <defs>
            <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="var(--primary)" stopOpacity="0.22" />
              <stop offset="100%" stopColor="var(--primary)" stopOpacity="0" />
            </linearGradient>
          </defs>
          {[25, 50, 75].map((y) => (
            <line key={y} x1="0" x2="100" y1={y} y2={y} stroke="var(--border)" strokeWidth="1" vectorEffect="non-scaling-stroke" />
          ))}
          {points.length > 1 ? <path d={`${line} L${lastX},100 L${firstX},100 Z`} fill={`url(#${gradientId})`} /> : null}
          <path d={line} fill="none" stroke="var(--primary)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" vectorEffect="non-scaling-stroke" />
        </svg>
        <div className="absolute inset-0 flex">
          {data.map((d) => (
            <div key={d.date} className="group relative h-full flex-1">
              <span className="pointer-events-none absolute inset-y-0 left-1/2 hidden w-px -translate-x-1/2 bg-border-strong group-hover:block" />
              <span
                className="pointer-events-none absolute left-1/2 hidden size-2.5 -translate-x-1/2 translate-y-1/2 rounded-full border-2 border-primary bg-card group-hover:block"
                style={{ bottom: `${heightPct(d[metric])}%` }}
              />
              <div className="pointer-events-none absolute bottom-full left-1/2 z-10 mb-1 hidden -translate-x-1/2 whitespace-nowrap rounded-sm border border-border-strong bg-popover px-2 py-1 text-[13px] shadow-lg group-hover:block">
                {d.date}: {fmt(d[metric])}
              </div>
            </div>
          ))}
        </div>
      </div>
      <div className="flex justify-between text-[13px] text-muted-foreground">
        <span>{data[0]?.date}</span>
        <span>{data[data.length - 1]?.date}</span>
      </div>
    </div>
  );
}

export function BillingScreen() {
  const usage = useUsage();
  const daily = useUsageDaily(30);
  const plans = usePlans();
  const sub = useSubscription();
  const invoices = useInvoices();
  const [redirecting, setRedirecting] = useState<string | null>(null);

  const go = async (key: string, fn: () => Promise<{ url: string }>) => {
    setRedirecting(key);
    try {
      const { url } = await fn();
      window.location.assign(url);
    } catch (e) {
      toast.error(errorMessage(e));
      setRedirecting(null);
    }
  };

  return (
    <PageBody>
      <PageHeader
        title="Billing and usage"
        description="Usage resets at the start of each billing period."
        actions={
          <Button variant="outline" loading={redirecting === "portal"} onClick={() => go("portal", api.billing.portal)}>
            Manage billing <ExternalLink />
          </Button>
        }
      />

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_320px]">
        <section className="flex flex-col">
          <SectionTitle>Daily usage</SectionTitle>
          <Card className="flex flex-1 flex-col">
            <CardContent className="flex-1">
              <QueryView query={daily} loading={<Skeleton className="h-52" />} isEmpty={(d) => d.length === 0} empty={<EmptyState compact title="No usage yet" />}>
                {(d) => <UsageChart data={d} />}
              </QueryView>
            </CardContent>
          </Card>
        </section>
        <section>
          <SectionTitle>This period</SectionTitle>
          <Card>
            <CardContent className="grid gap-4">
              {usage.isPending ? <Skeleton className="h-48" /> : usage.isError ? <ErrorState error={usage.error} compact onRetry={() => usage.refetch()} /> : (
                <>
                  <Meter label="AI tokens" used={usage.data.aiTokens.used} limit={usage.data.aiTokens.limit} format={formatNumber} />
                  <Meter label="Build minutes" used={usage.data.buildMinutes.used} limit={usage.data.buildMinutes.limit} />
                  <Meter label="Storage" used={usage.data.storage.usedBytes} limit={usage.data.storage.limitBytes} format={(n) => formatBytes(n)} />
                  <Meter label="Projects" used={usage.data.projects.used} limit={usage.data.projects.limit} />
                  <Meter label="Concurrent agent tasks" used={usage.data.concurrentAgentTasks.used} limit={usage.data.concurrentAgentTasks.limit} />
                  <p className="border-t border-border pt-3 text-[14px]">
                    Recorded AI cost: <span className="font-semibold tabular-nums">{formatUsd(usage.data.aiCostUsd)}</span>
                    <span className="block text-[13px] text-muted-foreground">Period ends {formatDateTime(usage.data.periodEnd)}</span>
                  </p>
                </>
              )}
            </CardContent>
          </Card>
        </section>
      </div>

      <section className="mt-8">
        <SectionTitle>
          Plans{" "}
          {/* The current plan is marked on its card; only status notes go here. */}
          {sub.data && (sub.data.cancelAtPeriodEnd || sub.data.status === "past_due") ? (
            <span className={cn("ml-1 font-normal", sub.data.status === "past_due" ? "text-destructive" : "text-muted-foreground")}>
              · {sub.data.status === "past_due" ? "Payment past due" : "Cancels at period end"}
            </span>
          ) : null}
        </SectionTitle>
        <QueryView query={plans} isEmpty={(d) => d.length === 0}>
          {(list) => (
            <div className="grid gap-3 md:grid-cols-3">
              {list.map((p) => {
                const current = p.id === sub.data?.planId;
                return (
                  <Card key={p.id} className={cn("flex flex-col p-5", current && "border-primary")}>
                    <div className="flex items-center justify-between">
                      <h3 className="text-base font-semibold">{p.name}</h3>
                      {current ? <Badge tone="primary">Current plan</Badge> : null}
                    </div>
                    <p className="mt-2 text-[28px] font-semibold tabular-nums tracking-tight">
                      {formatUsd(p.priceMonthlyUsd)}
                      <span className="text-[14px] font-normal text-muted-foreground"> / month</span>
                    </p>
                    <ul className="mt-3 grid gap-1.5 text-[14px]">
                      <li>{p.limits.aiTokensPerMonth ? `${formatNumber(p.limits.aiTokensPerMonth)} AI tokens` : "Unlimited AI tokens"}</li>
                      <li>{p.limits.buildMinutesPerMonth ? `${formatNumber(p.limits.buildMinutesPerMonth)} build minutes` : "Unlimited build minutes"}</li>
                      <li>{p.limits.projects ? `${p.limits.projects} projects` : "Unlimited projects"} · {formatBytes(p.limits.storageBytes, 0)} storage</li>
                      {p.features.map((f) => (
                        <li key={f} className="flex gap-1.5 text-muted-foreground"><Check className="mt-0.5 size-3.5 shrink-0 text-success" aria-hidden />{f}</li>
                      ))}
                    </ul>
                    <div className="mt-auto pt-4">
                      {current ? null : (
                        <Button className="w-full" variant="outline" loading={redirecting === p.id} onClick={() => go(p.id, () => api.billing.checkout(p.id))}>
                          Switch to {p.name}
                        </Button>
                      )}
                    </div>
                  </Card>
                );
              })}
            </div>
          )}
        </QueryView>
      </section>

      <section className="mt-8">
        <SectionTitle>Invoices</SectionTitle>
        <Card>
          <QueryView query={invoices} compact isEmpty={(d) => d.length === 0} empty={<EmptyState compact title="No invoices yet" />}>
            {(list) => (
              <Table>
                <THead><TR><TH>Date</TH><TH>Amount</TH><TH>Status</TH><TH><span className="sr-only">Download</span></TH></TR></THead>
                <TBody>
                  {list.map((i) => (
                    <TR key={i.id}>
                      <TD>{formatDateTime(i.issuedAt)}</TD>
                      <TD className="tabular-nums">{formatUsd(i.amountUsd)}</TD>
                      <TD><Badge tone={i.status === "paid" ? "success" : i.status === "open" ? "warning" : "neutral"}>{i.status}</Badge></TD>
                      <TD className="text-right">{i.pdfUrl ? <a href={i.pdfUrl} className="text-primary hover:underline">PDF</a> : <span className="text-[13px] text-muted-foreground">Not available</span>}</TD>
                    </TR>
                  ))}
                </TBody>
              </Table>
            )}
          </QueryView>
        </Card>
      </section>
    </PageBody>
  );
}
