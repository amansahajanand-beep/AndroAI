"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { ArrowDownToLine, Search } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/primitives";
import { cn } from "@/lib/utils";

function lineClass(line: string) {
  if (/^(e:|error:|FAILURE|BUILD FAILED)|\bFAILED\b|\[FAILED/.test(line)) return "text-destructive";
  if (/^(w:|warning:)|\[BLOCKED|\[UNVERIFIED/.test(line)) return "text-warning";
  if (/BUILD SUCCESSFUL|\[PASSED/.test(line)) return "text-success";
  if (/^> Task /.test(line)) return "text-muted-foreground";
  return "";
}

/**
 * Monospace log view with filter, line numbers and follow-tail.
 * Lines are rendered as text (never HTML) so log content can't inject markup.
 */
export function LogViewer({
  text,
  lines: lineProp,
  className,
  live,
  emptyText = "No output yet.",
}: {
  text?: string;
  lines?: string[];
  className?: string;
  live?: boolean;
  emptyText?: string;
}) {
  const lines = useMemo(() => lineProp ?? (text ? text.split("\n") : []), [lineProp, text]);
  const [filter, setFilter] = useState("");
  const [follow, setFollow] = useState(true);
  const scroller = useRef<HTMLDivElement>(null);

  const shown = useMemo(() => {
    const f = filter.toLowerCase();
    return lines.map((l, i) => [i + 1, l] as const).filter(([, l]) => !f || l.toLowerCase().includes(f));
  }, [lines, filter]);

  useEffect(() => {
    if (follow && scroller.current) scroller.current.scrollTop = scroller.current.scrollHeight;
  }, [shown, follow]);

  return (
    <div className={cn("flex min-h-0 flex-col", className)}>
      <div className="flex items-center gap-2 border-b border-border px-2 py-1.5">
        <div className="relative flex-1">
          <Search className="pointer-events-none absolute left-2 top-1/2 size-3.5 -translate-y-1/2 text-subtle-foreground" aria-hidden />
          <Input value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="Filter output" aria-label="Filter log output" className="h-7 pl-7 text-[13px]" />
        </div>
        {live ? (
          <span className="flex items-center gap-1.5 text-[13px] text-info">
            <span className="size-1.5 animate-pulse rounded-full bg-info" aria-hidden /> Live
          </span>
        ) : null}
        <Button
          variant={follow ? "secondary" : "subtle"}
          size="icon-xs"
          aria-pressed={follow}
          aria-label="Follow output"
          title="Follow output"
          onClick={() => setFollow((f) => !f)}
        >
          <ArrowDownToLine />
        </Button>
      </div>
      <div
        ref={scroller}
        onWheel={(e) => {
          if (e.deltaY < 0) setFollow(false);
        }}
        className="min-h-0 flex-1 overflow-auto bg-background/40 py-1.5 font-mono text-[13px] leading-5"
        role="log"
        aria-live={live ? "polite" : "off"}
      >
        {shown.length === 0 ? (
          <p className="px-3 text-muted-foreground">{lines.length ? "No lines match the filter." : emptyText}</p>
        ) : (
          shown.map(([n, l]) => (
            <div key={n} className="flex whitespace-pre hover:bg-surface-2/60">
              <span className="w-12 shrink-0 select-none pr-3 text-right text-subtle-foreground">{n}</span>
              <span className={cn("pr-4", lineClass(l))}>{l || " "}</span>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
