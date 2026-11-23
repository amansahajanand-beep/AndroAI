import { Hammer, ListChecks, ShieldCheck, type LucideIcon } from "lucide-react";

const POINTS: { icon: LucideIcon; text: string }[] = [
  { icon: ListChecks, text: "Plan, write, build, test and repair in one loop." },
  { icon: ShieldCheck, text: "Every agent change arrives as a diff you accept or reject." },
  { icon: Hammer, text: "Runs the real Gradle task, with honest test results." },
];

/** Decorative brand side of the Sign in / Register screens (large screens only). */
export function AuthBrandPanel() {
  return (
    <aside className="relative isolate hidden overflow-hidden border-l border-border bg-surface lg:flex lg:flex-col lg:justify-between lg:p-12 xl:p-16">
      <div aria-hidden className="pointer-events-none absolute inset-0 -z-10">
        <div className="absolute inset-0 bg-brand opacity-[0.14]" />
        <div className="absolute -right-24 -top-24 size-[28rem] rounded-full bg-brand-1/40 blur-[110px] animate-glow" />
        <div className="absolute -bottom-32 -left-16 size-[26rem] rounded-full bg-brand-3/30 blur-[110px] animate-glow [animation-delay:1.6s]" />
        <div className="dot-grid absolute inset-0 opacity-60 [mask-image:radial-gradient(ellipse_80%_70%_at_50%_40%,black,transparent)]" />
      </div>

      <div />

      <div className="max-w-lg">
        <h2 className="text-balance text-[clamp(2rem,3.2vw,2.75rem)] font-semibold leading-[1.1] tracking-[-0.03em]">
          Android development with an agent that{" "}
          <span className="text-brand animate-pan">builds what it writes.</span>
        </h2>
        <p className="mt-5 text-pretty text-[16px] leading-relaxed text-muted-foreground">
          Every edit waits for your review in a full browser IDE.
        </p>
        <ul className="stagger mt-9 grid gap-3.5">
          {POINTS.map((p, i) => (
            <li key={p.text} style={{ "--i": i + 2 } as React.CSSProperties} className="glass flex items-center gap-3.5 rounded-xl border border-border px-4 py-3 text-[14.5px] text-foreground/90">
              <span className="grid size-9 shrink-0 place-items-center rounded-lg bg-brand text-white shadow-[0_6px_16px_-6px_var(--brand-glow)]">
                <p.icon className="size-4" aria-hidden />
              </span>
              {p.text}
            </li>
          ))}
        </ul>
      </div>

      <p className="text-[13px] text-muted-foreground">Built for Android developers.</p>
    </aside>
  );
}
