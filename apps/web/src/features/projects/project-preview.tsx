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

/** A calm per-project accent: the project's hue at moderate chroma (no loud gradients). */
const accent = (h: number, l = 0.6, c = 0.14) => `oklch(${l} ${c} ${h})`;

/** Schematic screen content; one layout per project so a grid of cards has variety. */
function ScreenBody({ project, h }: { project: Project; h: number }) {
  if (project.isApkAnalysis) {
    // APK analyses: decompiled source, shown as code lines.
    const widths = ["w-3/4", "w-1/2", "w-5/6", "w-2/3", "w-1/3", "w-3/5", "w-4/5"];
    return (
      <div className="grid gap-[5px] px-2.5 pt-2">
        {widths.map((w, i) => (
          <i key={i} className={cn("h-[3px] rounded-full", w, i % 3 === 0 ? "bg-warning/50" : "bg-foreground/15")} style={{ marginLeft: `${(i % 3) * 6}px` }} />
        ))}
      </div>
    );
  }
  const layout = h % 3;
  if (layout === 0) {
    // List: avatar rows.
    return (
      <div className="grid gap-2 px-2.5 pt-2">
        {[0, 1, 2, 3].map((i) => (
          <div key={i} className="flex items-center gap-1.5">
            <i className="size-3.5 shrink-0 rounded-full" style={{ background: accent(h, 0.72, 0.09), opacity: 1 - i * 0.15 }} />
            <div className="grid flex-1 gap-[3px]">
              <i className="h-[3px] w-3/4 rounded-full bg-foreground/25" />
              <i className="h-[3px] w-1/2 rounded-full bg-foreground/12" />
            </div>
          </div>
        ))}
      </div>
    );
  }
  if (layout === 1) {
    // Cards: a hero card and two tiles.
    return (
      <div className="grid gap-1.5 px-2.5 pt-2">
        <div className="grid h-11 content-end gap-[3px] rounded-md p-1.5" style={{ background: accent(h, 0.62, 0.13) }}>
          <i className="h-[3px] w-1/2 rounded-full bg-white/80" />
          <i className="h-[3px] w-1/3 rounded-full bg-white/50" />
        </div>
        <div className="grid grid-cols-2 gap-1.5">
          {[0, 1].map((i) => (
            <div key={i} className="grid h-8 content-end gap-[3px] rounded-md bg-foreground/[0.06] p-1.5">
              <i className="h-[3px] w-3/4 rounded-full bg-foreground/25" />
            </div>
          ))}
        </div>
      </div>
    );
  }
  // Chart: a headline number and bars.
  const bars = [40, 65, 50, 85, 60, 75].map((v, i) => ((v + h + i * 13) % 55) + 35);
  return (
    <div className="px-2.5 pt-2">
      <i className="block h-[3px] w-1/3 rounded-full bg-foreground/15" />
      <i className="mt-1.5 block h-[6px] w-1/2 rounded-full bg-foreground/35" />
      <div className="mt-2.5 flex h-12 items-end gap-[3px]">
        {bars.map((v, i) => (
          <i key={i} className="flex-1 rounded-t-[2px]" style={{ height: `${v}%`, background: accent(h, 0.66, 0.12), opacity: i === 3 ? 1 : 0.55 }} />
        ))}
      </div>
    </div>
  );
}

/**
 * The project thumbnail: a calm neutral stage with a faint project tint, and a realistic phone
 * rising from the bottom edge showing a schematic screen of the app (status bar, app bar with
 * the project's initials and name, content, tab bar). Put it inside a `group` for the hover lift.
 */
export function ProjectPreview({ project, className }: { project: Project; className?: string }) {
  const h = hueOf(project.id);
  return (
    <div
      aria-hidden
      className={cn("relative h-36 overflow-hidden bg-surface-2", className)}
      style={{
        backgroundImage: `radial-gradient(60% 70% at 50% 100%, color-mix(in oklab, ${accent(h)} 14%, transparent), transparent 70%)`,
      }}
    >
      {/* Faint grid texture, fading out towards the edges. */}
      <div className="absolute inset-0 opacity-[0.35] [background-image:linear-gradient(to_right,var(--border)_1px,transparent_1px),linear-gradient(to_bottom,var(--border)_1px,transparent_1px)] [background-size:24px_24px] [mask-image:radial-gradient(ellipse_70%_70%_at_50%_45%,black,transparent)]" />

      <div className="absolute left-1/2 top-[14%] w-[8.25rem] -translate-x-1/2 transition-transform duration-500 ease-out group-hover:-translate-y-1.5">
        <div className="rounded-[1.35rem] bg-[#0e0e12] p-[4px] shadow-[0_18px_40px_-18px_rgb(0_0_0/0.55),0_0_0_1px_rgb(255_255_255/0.06)] transition-shadow duration-500 group-hover:shadow-[0_26px_50px_-18px_rgb(0_0_0/0.6),0_0_0_1px_rgb(255_255_255/0.08)]">
          <div className="h-[15rem] overflow-hidden rounded-[1.1rem] bg-background">
            {/* Status bar */}
            <div className="flex items-center justify-between px-3 pt-1.5 text-[6.5px] font-semibold text-foreground/70">
              <span>9:41</span>
              <span className="h-[7px] w-7 rounded-full bg-[#0e0e12]" />
              <span className="flex gap-[2px]">
                <i className="h-[4px] w-[4px] rounded-full bg-foreground/50" />
                <i className="h-[4px] w-[7px] rounded-[1px] bg-foreground/50" />
              </span>
            </div>
            {/* App bar */}
            <div className="mt-1.5 flex items-center gap-1.5 px-2.5">
              <span
                className="grid size-[18px] shrink-0 place-items-center rounded-[5px] text-[7px] font-bold text-white"
                style={{ background: project.isApkAnalysis ? "var(--warning)" : accent(h, 0.55, 0.15) }}
              >
                {project.isApkAnalysis ? <Package className="size-2.5" /> : initialsOf(project.name)}
              </span>
              <span className="truncate text-[7.5px] font-semibold text-foreground">{project.name}</span>
            </div>
            <ScreenBody project={project} h={h} />
          </div>
        </div>
      </div>

      {/* Soft fade where the phone meets the card's bottom edge. */}
      <div className="pointer-events-none absolute inset-x-0 bottom-0 h-8 bg-linear-to-t from-surface-2 to-transparent" />
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

/** Small square thumbnail used by the list view: the project's initials on a calm tinted tile. */
export function ProjectThumb({ project, className }: { project: Project; className?: string }) {
  const h = hueOf(project.id);
  return (
    <span
      aria-hidden
      className={cn("grid size-10 shrink-0 place-items-center rounded-xl border border-border text-[13px] font-semibold", className)}
      style={
        project.isApkAnalysis
          ? { background: "var(--warning-soft)", color: "var(--warning)" }
          : { background: `color-mix(in oklab, ${accent(h)} 14%, var(--surface))`, color: accent(h, 0.55, 0.15) }
      }
    >
      {project.isApkAnalysis ? <Package className="size-4" /> : initialsOf(project.name)}
    </span>
  );
}
