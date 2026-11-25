import { Hammer, ListChecks, ShieldCheck, type LucideIcon } from "lucide-react";

const POINTS: { icon: LucideIcon; text: string }[] = [
  { icon: ListChecks, text: "Plan, write, build, test and repair in one loop." },
  { icon: ShieldCheck, text: "Every agent change arrives as a diff you accept or reject." },
  { icon: Hammer, text: "Runs the real Gradle task, with honest test results." },
];

/**
 * Brand side of the auth screens (large screens only). It uses the same charcoal-to-glow
 * background as the Home hero, so signing in feels like the start of the same product.
 */
export function AuthBrandPanel() {
  return (
    <aside className="dark dash-hero relative hidden overflow-hidden text-white lg:flex lg:flex-col lg:justify-between lg:p-12 xl:p-16">
      <div />
      <div className="max-w-lg">
        <h2 className="text-balance text-[clamp(2rem,3.2vw,2.75rem)] font-semibold leading-[1.1] tracking-[-0.03em]">
          Android development with an agent that builds what it writes.
        </h2>
        <p className="mt-4 text-pretty text-[16px] leading-relaxed text-white/75">Every edit waits for your review in a full browser IDE.</p>
        <ul className="mt-8 grid gap-2.5">
          {POINTS.map((p) => (
            <li key={p.text} className="flex items-center gap-3 rounded-xl border border-white/10 bg-black/25 px-4 py-3 text-[14.5px] text-white/90 backdrop-blur">
              <span className="grid size-8 shrink-0 place-items-center rounded-lg bg-white/10 text-white">
                <p.icon className="size-4" aria-hidden />
              </span>
              {p.text}
            </li>
          ))}
        </ul>
      </div>
      <p className="text-[13px] text-white/60">Built for Android developers.</p>
    </aside>
  );
}
