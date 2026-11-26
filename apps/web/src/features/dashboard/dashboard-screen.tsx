"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { ArrowUp, FileArchive, Package } from "lucide-react";
import { useSession } from "@/lib/api/hooks";
import { usePrefersReducedMotion, useTypewriter } from "./use-typewriter";

const CHIP =
  "inline-flex h-8 items-center gap-1.5 rounded-full border border-border-strong px-3 text-[13px] text-muted-foreground transition-colors hover:bg-surface-3 hover:text-foreground";

/* ------------------------------------------------------------------ */
/* Home: a welcome heading and the build prompt, nothing else.         */
/* ------------------------------------------------------------------ */

/** Sample prompts the placeholder types out in turn (after "Ask AppPilot to "). */
const SAMPLE_PROMPTS = [
  "build a habit tracker with daily reminders and a weekly streak chart",
  "create an expense splitter for group trips that works offline",
  "make a recipe app with a shopping list and a cooking timer",
  "build a trail finder with maps, filters and saved hikes",
  "create a workout log with sets, reps and progress charts",
] as const;
const PLACEHOLDER_PREFIX = "Ask AppPilot to ";
const STATIC_PLACEHOLDER = `${PLACEHOLDER_PREFIX}${SAMPLE_PROMPTS[0]}…`;

function PromptHero({ firstName }: { firstName?: string }) {
  const router = useRouter();
  const [text, setText] = useState("");
  const [focused, setFocused] = useState(false);
  const reducedMotion = usePrefersReducedMotion();
  // Animate only while the box is idle: not focused and empty. It never touches the value itself.
  const animate = !focused && text === "" && !reducedMotion;
  const typed = useTypewriter(SAMPLE_PROMPTS, animate);
  const placeholder = animate ? `${PLACEHOLDER_PREFIX}${typed}` : STATIC_PLACEHOLDER;

  const submit = () => {
    const q = new URLSearchParams({ method: "prompt" });
    if (text.trim()) q.set("description", text.trim());
    router.push(`/projects/new?${q}`);
  };

  return (
    <section aria-label="Start a new app" className="dash-hero relative flex min-h-[calc(100dvh-3.5rem)] flex-col justify-center px-4 pb-24 pt-16 text-center sm:px-6 md:min-h-[calc(100dvh-1rem)]">
      {/* The hero is dark in both themes, so the prompt box always uses the dark tokens. */}
      <div className="dark">
        <h1 className="mx-auto max-w-3xl text-balance text-[clamp(1.875rem,4vw,2.75rem)] font-semibold leading-[1.1] tracking-[-0.035em] text-(--hero-fg)">
          What will you build today{firstName ? `, ${firstName}` : ""}?
        </h1>

        <form
          className="float-panel mx-auto mt-8 max-w-[720px] rounded-3xl border border-border bg-card p-3 text-left transition-colors focus-within:border-border-strong sm:p-4"
          onSubmit={(e) => {
            e.preventDefault();
            submit();
          }}
        >
          <label htmlFor="quick-prompt" className="sr-only">
            Describe the app
          </label>
          <textarea
            id="quick-prompt"
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                e.preventDefault();
                submit();
              }
            }}
            onFocus={() => setFocused(true)}
            onBlur={() => setFocused(false)}
            rows={2}
            placeholder={placeholder}
            className="block min-h-16 w-full resize-none bg-transparent px-1.5 py-1 text-[16px] leading-relaxed text-foreground outline-none placeholder:text-subtle-foreground"
          />
          <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
            <div className="flex flex-wrap items-center gap-1.5">
              <Link href="/projects/new?method=zip" className={CHIP}>
                <FileArchive className="size-3.5" aria-hidden /> Upload project
              </Link>
              <Link href="/projects/new?method=apk" className={CHIP}>
                <Package className="size-3.5" aria-hidden /> Analyze APK
              </Link>
            </div>
            <button
              type="submit"
              aria-label="Continue"
              title="Enter to continue · Shift+Enter for a new line"
              className="grid size-9 place-items-center rounded-full bg-foreground text-background transition-[transform,background-color] duration-150 hover:bg-foreground/85 active:scale-95"
            >
              <ArrowUp className="size-[18px]" aria-hidden />
            </button>
          </div>
        </form>
      </div>
    </section>
  );
}

export function DashboardScreen() {
  const session = useSession();
  const firstName = session.data?.user.name.split(" ")[0];

  return (
    <PromptHero firstName={firstName} />
  );
}
