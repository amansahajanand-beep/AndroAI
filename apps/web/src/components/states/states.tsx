"use client";

import * as React from "react";
import type { UseQueryResult } from "@tanstack/react-query";
import { ENDPOINTS } from "@apppilot/contracts";
import { AlertTriangle, Cable, Inbox, RotateCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/primitives";
import { errorMessage, isPendingBackend, type ApiError } from "@/lib/api/errors";
import { cn } from "@/lib/utils";

function StateFrame({
  icon,
  title,
  children,
  action,
  className,
  compact,
}: {
  icon: React.ReactNode;
  title: string;
  children?: React.ReactNode;
  action?: React.ReactNode;
  className?: string;
  compact?: boolean;
}) {
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center text-center",
        compact ? "gap-1.5 px-4 py-8" : "gap-2 px-6 py-16",
        className,
      )}
    >
      <div className="mb-1 grid size-11 place-items-center rounded-xl border border-border bg-surface-2 text-muted-foreground [&_svg]:size-5">{icon}</div>
      <p className="text-[15px] font-semibold tracking-tight">{title}</p>
      {children ? <div className="max-w-sm text-[14px] leading-relaxed text-muted-foreground">{children}</div> : null}
      {action ? <div className="mt-2">{action}</div> : null}
    </div>
  );
}

export function EmptyState(props: {
  title: string;
  children?: React.ReactNode;
  action?: React.ReactNode;
  icon?: React.ReactNode;
  className?: string;
  compact?: boolean;
}) {
  return <StateFrame icon={props.icon ?? <Inbox />} {...props} />;
}

export function ErrorState({
  error,
  onRetry,
  className,
  compact,
}: {
  error: unknown;
  onRetry?: () => void;
  className?: string;
  compact?: boolean;
}) {
  if (isPendingBackend(error)) return <PendingBackend error={error} className={className} compact={compact} />;
  return (
    <StateFrame
      icon={<AlertTriangle className="text-destructive" />}
      title="Couldn't load this"
      className={className}
      compact={compact}
      action={
        onRetry ? (
          <Button variant="outline" size="sm" onClick={onRetry}>
            <RotateCw /> Try again
          </Button>
        ) : undefined
      }
    >
      {errorMessage(error)}
    </StateFrame>
  );
}

/**
 * Shown when an endpoint isn't available yet. Names the endpoint and its
 * contract status so it's obvious this is an integration gap, not a bug.
 */
export function PendingBackend({
  error,
  endpoint,
  className,
  compact,
  children,
}: {
  error?: ApiError;
  endpoint?: keyof typeof ENDPOINTS;
  className?: string;
  compact?: boolean;
  children?: React.ReactNode;
}) {
  const key = endpoint ?? error?.endpoint;
  const spec = key ? ENDPOINTS[key] : undefined;
  return (
    <StateFrame icon={<Cable />} title="Waiting for backend" className={className} compact={compact}>
      <p>{children ?? error?.message ?? "This feature's API isn't available yet."}</p>
      {spec ? (
        <p className="mt-2 font-mono text-[12px] text-subtle-foreground">
          {spec.method} {spec.path}
          <br />
          owner: {spec.owner} · contract: {spec.status}
        </p>
      ) : null}
    </StateFrame>
  );
}

export function LoadingRows({ rows = 4, className }: { rows?: number; className?: string }) {
  return (
    <div className={cn("grid gap-2 p-5", className)} aria-busy="true" aria-label="Loading">
      {Array.from({ length: rows }, (_, i) => (
        <Skeleton key={i} className="h-10" style={{ opacity: 1 - i * 0.15 }} />
      ))}
    </div>
  );
}

/**
 * Renders the right state for a query: loading → error/pending → empty → data.
 */
export function QueryView<T>({
  query,
  children,
  loading,
  isEmpty,
  empty,
  compact,
  className,
}: {
  query: UseQueryResult<T>;
  children: (data: T) => React.ReactNode;
  loading?: React.ReactNode;
  isEmpty?: (data: T) => boolean;
  empty?: React.ReactNode;
  compact?: boolean;
  className?: string;
}) {
  if (query.isPending) return <>{loading ?? <LoadingRows className={className} />}</>;
  if (query.isError)
    return <ErrorState error={query.error} onRetry={() => query.refetch()} compact={compact} className={className} />;
  if (isEmpty?.(query.data)) return <>{empty ?? <EmptyState title="Nothing here yet" compact={compact} className={className} />}</>;
  return <>{children(query.data)}</>;
}
