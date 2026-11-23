import * as React from "react";
import { cn } from "@/lib/utils";

export function PageHeader({
  title,
  description,
  actions,
  className,
}: {
  title: React.ReactNode;
  description?: React.ReactNode;
  actions?: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("flex flex-wrap items-end justify-between gap-4 pb-8 animate-fade-up", className)}>
      <div className="min-w-0">
        <h1 className="text-[28px] font-semibold leading-tight tracking-[-0.025em] sm:text-[32px]">{title}</h1>
        {description ? <p className="mt-2 max-w-prose text-[15px] leading-relaxed text-muted-foreground">{description}</p> : null}
      </div>
      {actions ? <div className="flex items-center gap-2">{actions}</div> : null}
    </div>
  );
}

export function PageBody({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  // Desktop (lg+): 5% / 90% / 5% of the content area, with the 90% column
  // capped at 1600px and centred. Smaller breakpoints keep fixed gutters.
  return <div className={cn("mx-auto w-full px-4 py-8 sm:px-6 lg:w-[min(90%,1600px)] lg:px-0", className)} {...props} />;
}

export function SectionTitle({ children, action }: { children: React.ReactNode; action?: React.ReactNode }) {
  return (
    <div className="mb-3 flex items-center justify-between gap-2">
      <h2 className="font-display text-[16px] font-semibold tracking-tight">{children}</h2>
      {action}
    </div>
  );
}

/** Usage meter with explicit numbers (never colour alone). */
export function Meter({
  label,
  used,
  limit,
  format = (n) => String(n),
}: {
  label: string;
  used: number;
  limit: number | null;
  format?: (n: number) => string;
}) {
  const pct = limit ? Math.min(100, Math.round((used / limit) * 100)) : null;
  const tone = pct == null ? "bg-brand" : pct >= 90 ? "bg-destructive" : pct >= 75 ? "bg-warning" : "bg-brand";
  return (
    <div className="grid gap-1.5">
      <div className="flex items-baseline justify-between gap-2 text-[14px]">
        <span>{label}</span>
        <span className="tabular-nums text-muted-foreground">
          {format(used)}
          {limit != null ? ` of ${format(limit)}` : " · no limit"}
        </span>
      </div>
      <div
        className="h-2 overflow-hidden rounded-full bg-surface-3"
        role="meter"
        aria-label={label}
        aria-valuenow={used}
        aria-valuemin={0}
        aria-valuemax={limit ?? undefined}
      >
        <div className={cn("h-full rounded-full transition-[width] duration-700", tone)} style={{ width: `${pct ?? 0}%` }} />
      </div>
    </div>
  );
}
