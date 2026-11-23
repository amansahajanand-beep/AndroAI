import { cn } from "@/lib/utils";

/**
 * AppPilot mark: a heading indicator (the "pilot") on a gradient app tile.
 * The tile carries the brand gradient; the white tick is the agent's bearing.
 */
export function LogoMark({ className }: { className?: string }) {
  return (
    <span
      aria-hidden
      className={cn(
        "relative grid size-7 shrink-0 place-items-center rounded-[9px] bg-brand shadow-[0_6px_16px_-6px_var(--brand-glow)]",
        className,
      )}
    >
      <svg viewBox="0 0 24 24" className="size-[60%]">
        <path d="M12 3.5 18.5 19 12 15.6 5.5 19 12 3.5Z" fill="#fff" />
        <path d="M12 15.6V3.5" stroke="rgb(255 255 255 / 0.55)" strokeWidth="1.4" strokeLinecap="round" />
      </svg>
    </span>
  );
}

export function Logo({ className, collapsed }: { className?: string; collapsed?: boolean }) {
  return (
    <span className={cn("inline-flex items-center gap-2.5 font-display font-semibold tracking-tight", className)}>
      <LogoMark />
      {collapsed ? (
        <span className="sr-only">AppPilot AI</span>
      ) : (
        <span className="text-[17px] leading-none">
          AppPilot<span className="text-brand"> AI</span>
        </span>
      )}
    </span>
  );
}
