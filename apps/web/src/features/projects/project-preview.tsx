import type { AgentTask, AgentTaskStatus, Project } from "@apppilot/contracts";
import { Bot, CheckCircle2, Eye, Package } from "lucide-react";
import { cn } from "@/lib/utils";

export function hueOf(id: string) {
  let h = 0;
  for (let i = 0; i < id.length; i++) h = (h * 31 + id.charCodeAt(i)) % 360;
  return h;
}

export function initialsOf(name: string) {
  return name
    .split(/\s+/)
    .slice(0, 2)
    .map((p) => p[0]?.toUpperCase())
    .join("");
}

/**
 * A generated "device" preview: a unique hue per project, with the app's
 * initials on the screen. Put it inside a `group` element for the hover tilt.
 */
export function ProjectPreview({ project, className }: { project: Project; className?: string }) {
  const h = hueOf(project.id);
  return (
    <div
      aria-hidden
      className={cn("relative grid h-36 place-items-center overflow-hidden", className)}
      style={{
        backgroundImage: `radial-gradient(80% 90% at 20% 0%, oklch(0.62 0.2 ${h} / 0.55), transparent 70%), radial-gradient(70% 80% at 90% 100%, oklch(0.55 0.22 ${(h + 70) % 360} / 0.5), transparent 70%), linear-gradient(180deg, var(--surface-2), var(--surface))`,
      }}
    >
      <div className="dot-grid absolute inset-0 opacity-30" />
      <div className="relative h-[8.6rem] w-[4.7rem] translate-y-6 rounded-[14px] border border-white/20 bg-background/85 p-1.5 shadow-[0_18px_40px_-14px_rgb(0_0_0/0.55)] backdrop-blur transition-transform duration-500 group-hover:translate-y-3 group-hover:-rotate-3">
        <div
          className="grid h-8 place-items-center rounded-lg font-display text-[13px] font-semibold text-white"
          style={{ backgroundImage: `linear-gradient(135deg, oklch(0.6 0.2 ${h}), oklch(0.5 0.22 ${(h + 70) % 360}))` }}
        >
          {project.isApkAnalysis ? <Package className="size-4" /> : initialsOf(project.name)}
        </div>
        <div className="mt-1.5 grid gap-1">
          <i className="h-1.5 w-full rounded-full bg-foreground/15" />
          <i className="h-1.5 w-3/4 rounded-full bg-foreground/10" />
          <i className="h-5 w-full rounded-md bg-foreground/[0.07]" />
          <i className="h-5 w-full rounded-md bg-foreground/[0.07]" />
        </div>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Live app preview: the Projects page card header.                    */
/* ------------------------------------------------------------------ */

export type PreviewState =
  | { kind: "idle" }
  | { kind: "running"; label: string; percent: number | null }
  | { kind: "review"; label: string }
  | { kind: "failed"; label: string }
  | { kind: "succeeded" };

const TASK_LABEL: Partial<Record<AgentTaskStatus, string>> = {
  queued: "Queued",
  planning: "Planning",
  analyzing: "Analyzing",
  generating: "Generating",
  building: "Building",
  testing: "Testing",
  repairing: "Repairing",
};

/** Derives the card's visual state from data the card already has (plus the project's active agent task, if any). */
export function previewStateOf(project: Project, task?: AgentTask): PreviewState {
  if (task?.status === "reviewing") return { kind: "review", label: "Review changes" };
  if (task || project.activeTaskCount > 0 || project.status === "creating" || project.status === "analyzing") {
    const verb = task ? (TASK_LABEL[task.status] ?? "Working") : project.status === "analyzing" ? "Analyzing" : project.status === "creating" ? "Generating" : "Agent running";
    const step = task?.currentStep ?? task?.buildProgress?.phase ?? null;
    return { kind: "running", label: step ? `${verb} · ${step}` : verb, percent: task?.buildProgress?.percent ?? null };
  }
  if (project.lastBuild?.status === "running" || project.lastBuild?.status === "queued") {
    return { kind: "running", label: project.lastBuild.status === "queued" ? "Build queued" : "Building", percent: null };
  }
  if (project.status === "error") return { kind: "failed", label: "Setup failed" };
  if (project.lastBuild?.status === "failed") return { kind: "failed", label: "Build failed" };
  if (project.lastBuild?.status === "succeeded") return { kind: "succeeded" };
  return { kind: "idle" };
}

/** Keeps every project in the brand's violet family (indigo → violet → orchid). */
const violetHue = (id: string) => 255 + (hueOf(id) % 60);

type Layout = "list" | "cards" | "chart";
function layoutOf(project: Project): Layout {
  const text = `${project.name} ${project.description}`.toLowerCase();
  if (/expense|budget|financ|chart|stat|habit|track|fitness|health|money|ledger/.test(text)) return "chart";
  if (/recipe|shop|store|gallery|photo|product|food|menu|catalog|grocery|pantry/.test(text)) return "cards";
  return "list";
}

function PhoneScreen({ project, hue }: { project: Project; hue: number }) {
  const layout = layoutOf(project);
  const accent = `oklch(0.62 0.19 ${hue})`;
  return (
    <>
      {/* app bar: icon + name */}
      <div className="flex items-center gap-1.5 border-b border-foreground/10 px-1.5 pb-1.5 pt-1">
        <span
          className="grid size-4.5 shrink-0 place-items-center rounded-[5px] font-display text-[8px] font-bold text-white"
          style={{ backgroundImage: `linear-gradient(135deg, ${accent}, var(--brand-1))` }}
        >
          {project.isApkAnalysis ? <Package className="size-2.5" /> : initialsOf(project.name)}
        </span>
        <span className="min-w-0 truncate font-display text-[9.5px] font-semibold leading-none text-foreground">{project.name}</span>
      </div>
      <div className="grid gap-1 p-1.5">
        {layout === "list" &&
          [0, 1, 2].map((i) => (
            <span key={i} className="flex items-center gap-1 rounded-md bg-foreground/6 p-1">
              <i className="size-3 shrink-0 rounded-full" style={{ background: accent, opacity: 0.75 - i * 0.18 }} />
              <span className="grid flex-1 gap-0.5">
                <i className="h-1 rounded-full bg-foreground/25" style={{ width: `${80 - i * 15}%` }} />
                <i className="h-1 w-1/2 rounded-full bg-foreground/12" />
              </span>
            </span>
          ))}
        {layout === "cards" && (
          <span className="grid grid-cols-2 gap-1">
            {[0, 1, 2, 3].map((i) => (
              <span key={i} className="grid gap-0.5 rounded-md bg-foreground/6 p-0.5">
                <i className="h-4 rounded-[3px]" style={{ background: accent, opacity: 0.6 - (i % 2) * 0.2 }} />
                <i className="h-1 w-3/4 rounded-full bg-foreground/20" />
              </span>
            ))}
          </span>
        )}
        {layout === "chart" && (
          <>
            <span className="rounded-md bg-foreground/6 p-1">
              <i className="block h-1 w-1/2 rounded-full bg-foreground/25" />
              <span className="mt-1 flex h-6 items-end gap-0.75">
                {[45, 70, 35, 90, 60, 80].map((h, i) => (
                  <i key={i} className="flex-1 rounded-t-xs" style={{ height: `${h}%`, background: accent, opacity: 0.45 + (i % 3) * 0.18 }} />
                ))}
              </span>
            </span>
            <span className="flex items-center gap-1 rounded-md bg-foreground/6 p-1">
              <i className="size-2.5 rounded-full" style={{ background: accent }} />
              <i className="h-1 flex-1 rounded-full bg-foreground/20" />
            </span>
          </>
        )}
      </div>
    </>
  );
}

function StatusChip({ state }: { state: Exclude<PreviewState, { kind: "idle" }> }) {
  const base =
    "pointer-events-none inline-flex min-w-0 max-w-full items-center gap-1.5 rounded-full border border-white/10 bg-background/80 px-2.5 py-1 text-[12px] font-medium text-foreground shadow-[0_4px_14px_-6px_rgb(0_0_0/0.35)] backdrop-blur-md";
  if (state.kind === "running") {
    return (
      <span className={base}>
        <span className="relative grid size-2 shrink-0 place-items-center" aria-hidden>
          <span className="live-ping absolute inset-0 rounded-full bg-ai" />
          <span className="relative size-2 rounded-full bg-ai" />
        </span>
        <Bot className="size-3.5 shrink-0 text-ai" aria-hidden />
        <span className="truncate">{state.label}</span>
      </span>
    );
  }
  if (state.kind === "review") {
    return (
      <span className={cn(base, "border-ai/30 bg-ai-soft text-ai")}>
        <Eye className="size-3.5 shrink-0" aria-hidden />
        <span className="truncate">{state.label}</span>
      </span>
    );
  }
  if (state.kind === "failed") {
    return (
      <span className={base}>
        <span className="size-2 shrink-0 rounded-full bg-destructive" aria-hidden />
        <span className="truncate">{state.label}</span>
      </span>
    );
  }
  return (
    <span className={base}>
      <CheckCircle2 className="size-3.5 shrink-0 text-success" aria-hidden />
      <span className="truncate">Build passed</span>
    </span>
  );
}

/**
 * The card header on the Projects page: a soft violet aurora, a tilted phone
 * that shows the app's name, icon and a layout hinting at what it does, plus
 * a status bar and progress line while an agent is working. Decorative parts
 * are aria-hidden; the status text stays readable by assistive tech.
 * Put it inside a `group` element for the hover motion; `menu` renders top-right.
 */
export function LiveAppPreview({ project, task, menu }: { project: Project; task?: AgentTask; menu?: React.ReactNode }) {
  const hue = violetHue(project.id);
  const state = previewStateOf(project, task);
  return (
    <div className="relative h-40 overflow-hidden border-b border-border">
      <div
        aria-hidden
        className="absolute inset-0"
        style={{
          backgroundImage: `radial-gradient(70% 90% at 18% 0%, color-mix(in oklab, var(--brand-1) 26%, transparent), transparent 70%), radial-gradient(60% 80% at 95% 100%, oklch(0.66 0.16 ${hue} / 0.22), transparent 70%), linear-gradient(180deg, var(--surface-2), var(--surface))`,
        }}
      />
      {/* tilted phone, left of centre */}
      <div
        aria-hidden
        className="absolute left-[14%] top-12 w-[6.4rem] -rotate-6 rounded-[16px] border border-foreground/10 bg-background/90 p-1 shadow-[0_22px_44px_-18px_color-mix(in_oklab,var(--brand-1)_55%,black)] backdrop-blur transition-transform duration-500 ease-out group-hover:-translate-y-2 group-hover:rotate-0"
      >
        <div className="mx-auto mb-1 h-1 w-6 rounded-full bg-foreground/15" />
        <PhoneScreen project={project} hue={hue} />
      </div>
      {/* a floating "code" card on the right, echoing that this is a real, editable project */}
      <div
        aria-hidden
        className="absolute right-[10%] top-[3.6rem] hidden w-30 rotate-3 rounded-xl border border-foreground/10 bg-background/70 p-2 shadow-[0_14px_30px_-16px_rgb(0_0_0/0.45)] backdrop-blur transition-transform duration-500 ease-out group-hover:translate-y-1 group-hover:rotate-0 min-[380px]:block"
      >
        <span className="flex gap-1">
          <i className="size-1.5 rounded-full bg-destructive/60" />
          <i className="size-1.5 rounded-full bg-warning/60" />
          <i className="size-1.5 rounded-full bg-success/60" />
        </span>
        <span className="mt-1.5 grid gap-1">
          <i className="h-1 w-3/4 rounded-full" style={{ background: `oklch(0.66 0.16 ${hue} / 0.7)` }} />
          <i className="ml-2 h-1 w-1/2 rounded-full bg-foreground/20" />
          <i className="ml-2 h-1 w-2/3 rounded-full bg-foreground/15" />
          <i className="h-1 w-1/3 rounded-full bg-foreground/20" />
        </span>
      </div>

      {/* status bar + actions */}
      <div className="pointer-events-none absolute inset-x-2.5 top-2.5 z-10 flex items-start justify-between gap-2">
        <div className="min-w-0" role={state.kind === "running" ? "status" : undefined}>
          {state.kind !== "idle" ? <StatusChip state={state} /> : null}
        </div>
        {menu ? (
          <div className="pointer-events-auto relative z-20 shrink-0 opacity-0 transition-opacity duration-200 group-hover:opacity-100 focus-within:opacity-100 has-data-[state=open]:opacity-100 [@media(hover:none)]:opacity-100">
            {menu}
          </div>
        ) : null}
      </div>

      {/* progress line while an agent or build is running */}
      {state.kind === "running" ? (
        <div aria-hidden className="absolute inset-x-0 bottom-0 h-0.75 overflow-hidden bg-foreground/6">
          {state.percent != null ? (
            <div className="h-full bg-brand transition-[width] duration-700" style={{ width: `${Math.max(4, Math.min(100, state.percent))}%` }} />
          ) : (
            <div className="live-progress h-full w-2/5 rounded-full bg-brand" />
          )}
        </div>
      ) : null}
    </div>
  );
}

/** Small square thumbnail used by the list view. */
export function ProjectThumb({ project, className }: { project: Project; className?: string }) {
  const h = hueOf(project.id);
  return (
    <span
      aria-hidden
      className={cn("grid size-10 shrink-0 place-items-center rounded-xl font-display text-[13px] font-semibold text-white shadow-[0_6px_16px_-8px_rgb(0_0_0/0.5)]", className)}
      style={{ backgroundImage: `linear-gradient(135deg, oklch(0.62 0.2 ${h}), oklch(0.5 0.22 ${(h + 70) % 360}))` }}
    >
      {project.isApkAnalysis ? <Package className="size-4" /> : initialsOf(project.name)}
    </span>
  );
}
