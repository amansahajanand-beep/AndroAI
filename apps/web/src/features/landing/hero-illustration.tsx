import { CheckCircle2, Hammer, ListChecks, Sparkles, TestTube2 } from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * Static, decorative illustration of the IDE reviewing an agent change.
 * Built in HTML so it follows the theme; hidden from assistive tech.
 */
const CODE: { n: number; text: string; kind?: "add" | "ctx" }[] = [
  { n: 17, text: "@Composable" },
  { n: 18, text: "fun TrailListScreen(trails: List<Trail>) {" },
  { n: 19, text: '    var query by remember { mutableStateOf("") }', kind: "add" },
  { n: 20, text: "    val visible = trails.filter {", kind: "add" },
  { n: 21, text: "        it.name.contains(query, ignoreCase = true)", kind: "add" },
  { n: 22, text: "    }", kind: "add" },
  { n: 23, text: "    Column(Modifier.padding(16.dp)) {" },
  { n: 24, text: "        TrailSearchBar(query, onQueryChange = { query = it })", kind: "add" },
  { n: 25, text: "        LazyColumn {" },
  { n: 26, text: "            items(visible, key = { it.id }) { trail ->", kind: "add" },
];

const TREE = [
  { name: "app", depth: 0 },
  { name: "ui", depth: 1 },
  { name: "TrailListScreen.kt", depth: 2, mark: "M", ai: true, selected: true },
  { name: "TrailSearchBar.kt", depth: 2, mark: "A", ai: true },
  { name: "theme", depth: 2 },
  { name: "data", depth: 1 },
  { name: "build.gradle.kts", depth: 1 },
];

const STEPS = [
  { icon: ListChecks, label: "Planned 2 steps", done: true },
  { icon: Sparkles, label: "Wrote 2 files", done: true },
  { icon: Hammer, label: ":app:assembleDebug", done: true },
  { icon: TestTube2, label: "Unit tests 2/2 passed", done: true },
];

const TOKEN = /(@\w+|"[^"]*"|\b(?:fun|var|val|by)\b|\b[A-Z]\w*\b)/g;
const KEYWORDS = new Set(["fun", "var", "val", "by"]);

/** Minimal Kotlin colouring using theme tokens, so it stays readable in both themes. */
function Highlight({ text }: { text: string }) {
  return (
    <>
      {text.split(TOKEN).map((part, i) => {
        if (i % 2 === 0) return part;
        const tone = part.startsWith("@")
          ? "text-warning"
          : part.startsWith('"')
            ? "text-success"
            : KEYWORDS.has(part)
              ? "text-primary"
              : "text-info";
        return (
          <span key={i} className={tone}>
            {part}
          </span>
        );
      })}
    </>
  );
}

export function HeroIllustration({ className }: { className?: string }) {
  return (
    <div
      aria-hidden
      className={cn(
        "relative rounded-2xl bg-linear-to-b from-brand-2/60 via-border-strong to-border/20 p-px",
        "shadow-[0_40px_90px_-50px_rgb(15_20_40/0.4)] dark:shadow-[0_40px_100px_-40px_rgb(0_0_0/0.85)]",
        className,
      )}
    >
      <div className="absolute -right-3 -top-4 z-10 hidden items-center gap-1.5 rounded-full border border-success/30 bg-card px-3 py-1.5 text-[12px] font-medium text-success shadow-pop animate-float sm:flex">
        <CheckCircle2 className="size-3.5" /> Build succeeded
      </div>
      <div className="absolute -left-3 bottom-16 z-10 hidden items-center gap-1.5 rounded-full border border-ai/30 bg-card px-3 py-1.5 text-[12px] font-medium text-ai shadow-pop animate-float [animation-delay:2s] md:flex">
        <Sparkles className="size-3.5" /> 2 files written by agent
      </div>
      <div className="overflow-hidden rounded-[19px] bg-surface">
        <div className="flex h-11 items-center gap-3 border-b border-border bg-surface-2/60 px-4 text-[12px] text-muted-foreground">
          <span className="flex gap-1.5">
            <i className="size-2.5 rounded-full bg-destructive/70" />
            <i className="size-2.5 rounded-full bg-warning/70" />
            <i className="size-2.5 rounded-full bg-success/70" />
          </span>
          <span>Trailhead · Review changes</span>
        </div>
        <div className="grid min-h-[320px] grid-cols-[180px_1fr] md:grid-cols-[210px_1fr_270px]">
          <div className="hidden border-r border-border p-2.5 font-mono text-[11.5px] sm:block">
            {TREE.map((t) => (
              <div
                key={t.name}
                className={cn("flex h-6 items-center justify-between rounded-sm pr-1.5", t.selected && "bg-surface-3")}
                style={{ paddingLeft: 6 + t.depth * 12 }}
              >
                <span className={cn("truncate", t.ai ? "text-ai" : "text-muted-foreground")}>{t.name}</span>
                {t.mark ? (
                  <span className={cn("text-[11px]", t.mark === "A" ? "text-git-added" : "text-git-modified")}>{t.mark}</span>
                ) : null}
              </div>
            ))}
          </div>
          <div className="col-span-2 overflow-hidden bg-background/40 py-3 font-mono text-[13px] leading-6 sm:col-span-1">
            {CODE.map((l) => (
              <div key={l.n} className={cn("flex whitespace-pre", l.kind === "add" && "bg-ai-soft")}>
                <span className={cn("w-1 shrink-0", l.kind === "add" ? "bg-ai" : "bg-transparent")} />
                <span className="w-10 shrink-0 pr-3 text-right text-subtle-foreground">{l.n}</span>
                <span className="overflow-hidden text-ellipsis whitespace-pre pr-4">
                  <Highlight text={l.text} />
                </span>
              </div>
            ))}
          </div>
          <div className="hidden flex-col border-l border-border p-4 md:flex">
            <p className="text-[13px] font-medium">Add trail search</p>
            <ul className="mt-3 grid gap-2.5">
              {STEPS.map((s) => (
                <li key={s.label} className="flex items-center gap-2 text-[13px] text-muted-foreground">
                  <s.icon className="size-3.5 text-ai" />
                  <span className="flex-1 truncate">{s.label}</span>
                  <CheckCircle2 className="size-3.5 text-success" />
                </li>
              ))}
            </ul>
            <div className="mt-auto flex gap-2 pt-4">
              <span className="flex-1 rounded-lg bg-ai px-2 py-1.5 text-center text-[13px] font-medium text-ai-foreground shadow-[0_6px_16px_-8px_var(--ai)]">
                Accept 2 files
              </span>
              <span className="rounded-lg border border-border-strong px-2 py-1.5 text-[13px]">Reject</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
