"use client";

import { useRef } from "react";
import { Code2, Smartphone } from "lucide-react";
import { Tooltip } from "@/components/ui/overlays";
import { cn } from "@/lib/utils";
import type { WorkspaceView } from "@/stores/ide-store";
import { ALT, MOD } from "./shortcuts";

const TABS: { value: WorkspaceView; label: string; icon: typeof Code2 }[] = [
  { value: "preview", label: "Preview", icon: Smartphone },
  { value: "code", label: "Code", icon: Code2 },
];

/**
 * Preview | Code switch for the toolbar. A sliding pill marks the active view.
 * Keyboard: arrow keys move between the two tabs, like any tablist.
 */
export function ViewToggle({
  value,
  onChange,
  previewDisabledReason,
}: {
  value: WorkspaceView;
  onChange: (v: WorkspaceView) => void;
  /** When set, Preview can't be opened and this explains why. */
  previewDisabledReason?: string;
}) {
  const refs = useRef<Partial<Record<WorkspaceView, HTMLButtonElement | null>>>({});
  const activeIndex = value === "preview" ? 0 : 1;

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
    e.preventDefault();
    const next = TABS[(activeIndex + (e.key === "ArrowRight" ? 1 : TABS.length - 1)) % TABS.length]!.value;
    if (next === "preview" && previewDisabledReason) return;
    onChange(next);
    refs.current[next]?.focus();
  };

  return (
    <div
      role="tablist"
      aria-label="Workspace view"
      onKeyDown={onKeyDown}
      className="relative inline-grid h-8 shrink-0 grid-cols-2 rounded-full border border-border bg-surface-2 p-0.5"
    >
      <span
        aria-hidden
        className="absolute inset-y-0.5 left-0.5 w-[calc(50%-2px)] rounded-full bg-surface-3 shadow-[0_1px_2px_rgb(0_0_0/0.3)] transition-transform duration-200 ease-out"
        style={{ transform: `translateX(${activeIndex * 100}%)` }}
      />
      {TABS.map(({ value: v, label, icon: Icon }) => {
        const selected = v === value;
        const disabled = v === "preview" && !!previewDisabledReason;
        const button = (
          <button
            key={v}
            ref={(el) => {
              refs.current[v] = el;
            }}
            type="button"
            role="tab"
            id={`view-tab-${v}`}
            aria-selected={selected}
            aria-controls={`view-panel-${v}`}
            aria-disabled={disabled || undefined}
            tabIndex={selected ? 0 : -1}
            onClick={() => (disabled ? undefined : onChange(v))}
            className={cn(
              "relative z-10 inline-flex h-7 min-w-[5.25rem] items-center justify-center gap-1.5 rounded-full px-3 text-[13px] font-medium outline-none transition-colors duration-200 focus-visible:ring-2 focus-visible:ring-ring",
              selected ? "text-foreground" : "text-muted-foreground hover:text-foreground",
              disabled && "cursor-not-allowed opacity-50 hover:text-muted-foreground",
            )}
          >
            <Icon className={cn("size-3.5 transition-colors duration-200", selected && "text-primary")} aria-hidden />
            {label}
          </button>
        );
        const tip = disabled ? previewDisabledReason : v === "preview" ? "Show the running app" : "Back to the code editor";
        return (
          <Tooltip key={v} content={tip} shortcut={`${MOD}+${ALT}+P`}>
            {button}
          </Tooltip>
        );
      })}
    </div>
  );
}
