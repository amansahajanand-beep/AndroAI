"use client";

import { useState } from "react";
import { AiOrbit } from "@/components/brand/ai-orbit";
import { Tooltip } from "@/components/ui/overlays";
import { usePlans, useSubscription } from "@/lib/api/hooks";
import { cn } from "@/lib/utils";
import { PlansDialog } from "./plans-dialog";

/** The sidebar's "Upgrade plan" card; opens the plans modal. Collapsed sidebar: just the orb. */
export function UpgradeCard({ collapsed, className }: { collapsed?: boolean; className?: string }) {
  const [open, setOpen] = useState(false);
  const plans = usePlans();
  const sub = useSubscription();
  const current = plans.data?.find((p) => p.id === sub.data?.planId);
  const top = plans.data && plans.data.length > 0 && current ? current.priceMonthlyUsd >= Math.max(...plans.data.map((p) => p.priceMonthlyUsd)) : false;
  const title = top ? "View plans" : "Upgrade plan";
  const subtitle = current ? `You're on ${current.name}` : "More AI tokens and builds";

  return (
    <>
      {collapsed ? (
        <Tooltip content={title} side="right">
          <button
            type="button"
            onClick={() => setOpen(true)}
            aria-label={title}
            className={cn("grid size-10 place-items-center rounded-xl outline-none transition-colors hover:bg-surface-3 focus-visible:ring-2 focus-visible:ring-ring", className)}
          >
            <AiOrbit size={30} />
          </button>
        </Tooltip>
      ) : (
        <button
          type="button"
          onClick={() => setOpen(true)}
          className={cn(
            "group flex w-full items-center gap-3 rounded-xl border border-border bg-surface-2 px-3 py-2.5 text-left outline-none transition-colors duration-200 hover:border-border-strong hover:bg-surface-3 focus-visible:ring-2 focus-visible:ring-ring",
            className,
          )}
        >
          <AiOrbit size={40} />
          <span className="min-w-0 flex-1">
            <span className="block text-[13.5px] font-semibold text-foreground">{title}</span>
            <span className="block truncate text-[12px] text-muted-foreground">{subtitle}</span>
          </span>
        </button>
      )}
      <PlansDialog open={open} onOpenChange={setOpen} />
    </>
  );
}
