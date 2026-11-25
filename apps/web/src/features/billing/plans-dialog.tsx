"use client";

import Link from "next/link";
import { useState } from "react";
import type { Plan } from "@apppilot/contracts";
import { Check, ExternalLink } from "lucide-react";
import { toast } from "sonner";
import { AiOrbit } from "@/components/brand/ai-orbit";
import { ErrorState } from "@/components/states/states";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogTitle, Tooltip } from "@/components/ui/overlays";
import { Skeleton } from "@/components/ui/primitives";
import { api } from "@/lib/api/client";
import { errorMessage } from "@/lib/api/errors";
import { usePlans, useSubscription } from "@/lib/api/hooks";
import { cn, formatBytes, formatNumber, formatUsd } from "@/lib/utils";

type Interval = "monthly" | "yearly";

/**
 * The plans don't carry yearly prices and checkout takes only a plan id, so yearly billing can't be
 * offered honestly yet. The toggle shows it, disabled, with the reason.
 */
const YEARLY_UNAVAILABLE = "Yearly billing isn't available yet: plans only have monthly prices.";

function limitLines(p: Plan) {
  return [
    p.limits.buildMinutesPerMonth ? `${formatNumber(p.limits.buildMinutesPerMonth)} build minutes / month` : "Unlimited build minutes",
    p.limits.projects ? `${p.limits.projects} projects` : "Unlimited projects",
    `${formatBytes(p.limits.storageBytes, 0)} storage`,
    `${p.limits.concurrentAgentTasks} agent task${p.limits.concurrentAgentTasks === 1 ? "" : "s"} at a time`,
  ];
}

function PlanCard({
  plan,
  index,
  current,
  recommended,
  currentPrice,
  redirecting,
  onChoose,
}: {
  plan: Plan;
  index: number;
  current: boolean;
  recommended: boolean;
  currentPrice: number | null;
  redirecting: boolean;
  onChoose: () => void;
}) {
  const upgrade = currentPrice == null || plan.priceMonthlyUsd > currentPrice;
  return (
    <article
      style={{ "--i": index } as React.CSSProperties}
      className={cn(
        "relative flex min-w-0 flex-col rounded-xl border bg-card p-5 transition-colors duration-200",
        recommended ? "border-primary/60" : current ? "border-border-strong" : "border-border hover:border-border-strong",
      )}
    >
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-[15px] font-semibold">{plan.name}</h3>
        {current ? (
          <span className="rounded-full bg-surface-3 px-2 py-0.5 text-[11.5px] font-medium text-muted-foreground">Current plan</span>
        ) : recommended ? (
          <span className="rounded-full bg-primary-soft px-2 py-0.5 text-[11.5px] font-medium text-primary">Recommended</span>
        ) : null}
      </div>

      <p className="mt-3 flex items-baseline gap-1">
        <span className="text-[32px] font-semibold tabular-nums tracking-tight">{formatUsd(plan.priceMonthlyUsd)}</span>
        <span className="text-[13.5px] text-muted-foreground">/ month</span>
      </p>

      {/* Credits: the plan's monthly AI token allowance. */}
      <p className="mt-3 rounded-lg bg-surface-2 px-3 py-2 text-[13.5px]">
        <span className="font-semibold">{plan.limits.aiTokensPerMonth ? formatNumber(plan.limits.aiTokensPerMonth) : "Unlimited"}</span>{" "}
        <span className="text-muted-foreground">AI tokens / month</span>
      </p>

      <ul className="mt-4 grid gap-2 text-[13.5px]">
        {[...limitLines(plan), ...plan.features].map((f) => (
          <li key={f} className="flex gap-2">
            <Check className="mt-0.5 size-3.5 shrink-0 text-success" aria-hidden />
            <span className="text-foreground/90">{f}</span>
          </li>
        ))}
      </ul>

      <div className="mt-auto pt-5">
        {current ? (
          <Button variant="secondary" className="w-full" disabled>
            Your current plan
          </Button>
        ) : (
          <Button className="w-full" variant={recommended ? "default" : "outline"} loading={redirecting} onClick={onChoose}>
            {upgrade ? `Upgrade to ${plan.name}` : `Switch to ${plan.name}`}
          </Button>
        )}
      </div>
    </article>
  );
}

/**
 * Large plans modal. Data and checkout are the existing billing API (plans, subscription,
 * provider-hosted checkout/portal redirects), exactly as the Billing page uses them.
 */
export function PlansDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const plans = usePlans();
  const sub = useSubscription();
  const [interval, setBillingInterval] = useState<Interval>("monthly");
  const [redirecting, setRedirecting] = useState<string | null>(null);

  // Same redirect flow as the Billing page.
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

  const list = [...(plans.data ?? [])].sort((a, b) => a.priceMonthlyUsd - b.priceMonthlyUsd);
  const current = list.find((p) => p.id === sub.data?.planId) ?? null;
  // Recommend the next plan up from the current one (or the middle plan when we don't know).
  const recommendedId = current ? list.find((p) => p.priceMonthlyUsd > current.priceMonthlyUsd)?.id : list[Math.floor(list.length / 2)]?.id;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="dark flex max-h-[90dvh] w-[calc(100%-1.5rem)] max-w-5xl flex-col gap-0 overflow-hidden p-0 text-foreground">
        {/* Header */}
        <div className="flex shrink-0 flex-col items-center border-b border-border px-6 pb-5 pt-7 text-center">
          <AiOrbit size={72} />
          <DialogTitle className="mt-4 text-[22px] font-semibold tracking-[-0.02em]">Upgrade your AppPilot</DialogTitle>
          <DialogDescription className="mt-1.5 max-w-md text-[14px] text-muted-foreground">
            More AI tokens, build minutes and projects for bigger Android apps.
          </DialogDescription>

          <div role="radiogroup" aria-label="Billing period" className="mt-5 inline-flex rounded-full border border-border-strong p-0.5">
            <button
              type="button"
              role="radio"
              aria-checked={interval === "monthly"}
              onClick={() => setBillingInterval("monthly")}
              className={cn(
                "h-8 rounded-full px-4 text-[13px] font-medium outline-none transition-colors focus-visible:ring-2 focus-visible:ring-ring",
                interval === "monthly" ? "bg-surface-3 text-foreground" : "text-muted-foreground hover:text-foreground",
              )}
            >
              Monthly
            </button>
            <Tooltip content={YEARLY_UNAVAILABLE}>
              <button
                type="button"
                role="radio"
                aria-checked={false}
                aria-disabled
                aria-describedby="yearly-unavailable"
                className="inline-flex h-8 cursor-not-allowed items-center gap-1.5 rounded-full px-4 text-[13px] font-medium text-muted-foreground/60 outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                Yearly
                <span className="rounded-full bg-surface-3 px-1.5 text-[10.5px] text-muted-foreground">Soon</span>
              </button>
            </Tooltip>
          </div>
          <span id="yearly-unavailable" className="sr-only">
            {YEARLY_UNAVAILABLE}
          </span>
        </div>

        {/* Plans (scrolls inside the modal) */}
        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-5 sm:px-6">
          {plans.isPending || sub.isPending ? (
            <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3" aria-busy="true" aria-label="Loading plans">
              {[0, 1, 2].map((i) => (
                <Skeleton key={i} className="h-96 rounded-xl" />
              ))}
            </div>
          ) : plans.isError ? (
            <ErrorState error={plans.error} onRetry={() => plans.refetch()} />
          ) : list.length === 0 ? (
            <p className="py-12 text-center text-[14px] text-muted-foreground">No plans are available right now.</p>
          ) : (
            <div className={cn("stagger grid gap-4", list.length > 1 && "md:grid-cols-2", list.length > 2 && "lg:grid-cols-3")}>
              {list.map((p, i) => (
                <PlanCard
                  key={p.id}
                  plan={p}
                  index={i}
                  current={p.id === current?.id}
                  recommended={p.id === recommendedId}
                  currentPrice={current?.priceMonthlyUsd ?? null}
                  redirecting={redirecting === p.id}
                  onChoose={() => go(p.id, () => api.billing.checkout(p.id))}
                />
              ))}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex shrink-0 flex-wrap items-center justify-between gap-2 border-t border-border px-6 py-3 text-[12.5px] text-muted-foreground">
          <span>Payments are handled by our billing provider. Card details never touch AppPilot.</span>
          <span className="flex items-center gap-1">
            <Button asChild variant="subtle" size="sm">
              <Link href="/billing" onClick={() => onOpenChange(false)}>
                Billing and usage
              </Link>
            </Button>
            <Button variant="subtle" size="sm" loading={redirecting === "portal"} onClick={() => go("portal", api.billing.portal)}>
              Manage billing <ExternalLink />
            </Button>
          </span>
        </div>
      </DialogContent>
    </Dialog>
  );
}
