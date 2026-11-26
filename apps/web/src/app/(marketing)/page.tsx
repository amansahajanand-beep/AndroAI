import Link from "next/link";
import {
  CircleCheckBig,
  FileArchive,
  FileDiff,
  Hammer,
  ListChecks,
  MessageSquareText,
  Package,
  Sparkles,
  TestTube2,
  Wrench,
} from "lucide-react";
import { Logo } from "@/components/brand/logo";
import { ThemeToggle } from "@/components/layout/chrome";
import { PilotFlight } from "@/features/landing/pilot-flight";
import { LandingAccount, OpenAppButton, StartProjectButton } from "@/components/layout/open-app-button";
import { HeroIllustration } from "@/features/landing/hero-illustration";
import { RedirectSignedIn } from "@/features/landing/redirect-signed-in";

const NAV = [
  { href: "#start", label: "Get started" },
  { href: "#agent", label: "Agent loop" },
  { href: "#trust", label: "Trust" },
];

const TECH = ["Kotlin", "Java", "Jetpack Compose", "Gradle", "Android Views", "Room", "Hilt", "Coroutines", "Retrofit", "Material 3"];

const ENTRY_POINTS = [
  {
    icon: MessageSquareText,
    title: "Describe a new app",
    body: "Name it, describe what it does, pick Kotlin or Java and Compose or XML views. The agent generates a Gradle project you can open, build and change.",
    tone: "primary",
  },
  {
    icon: FileArchive,
    title: "Upload an Android Studio project",
    body: "Drop in a ZIP of your project. We validate the Gradle setup, map the modules and versions, and let the agent work on your real source.",
    tone: "ai",
  },
  {
    icon: Package,
    title: "Inspect an APK",
    body: "See the package, SDK levels, permissions, components and libraries inside any APK. This is analysis of compiled output — not a way to recover or edit the original source.",
    tone: "info",
  },
] as const;

const LOOP = [
  { name: "Plan", icon: ListChecks, body: "Breaks your request into steps and lists the files it expects to touch." },
  { name: "Write", icon: Sparkles, body: "Edits Kotlin, Java, XML and Gradle files in an isolated workspace." },
  { name: "Build", icon: Hammer, body: "Runs the real Gradle task for the variant you chose." },
  { name: "Test", icon: TestTube2, body: "Runs unit, instrumentation and emulator tests with screenshots." },
  { name: "Repair", icon: Wrench, body: "Reads compiler and test failures and tries again, up to a limit you can see." },
];

const TONE: Record<string, string> = {
  primary: "bg-primary-soft text-primary ring-primary/25",
  ai: "bg-ai-soft text-ai ring-ai/25",
  info: "bg-info-soft text-info ring-info/25",
};

/** The pilot arrow: the AppPilot mark, scaled up and floated into the headline. */
function PilotGlyph({ className }: { className?: string }) {
  return (
    <PilotFlight className={className}>
      <svg viewBox="0 0 64 64" aria-hidden className="pilot-float block size-full">
        <defs>
          <linearGradient id="pilot-glyph" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0" stopColor="var(--brand-3)" />
            <stop offset="1" stopColor="var(--brand-1)" />
          </linearGradient>
          <linearGradient id="pilot-sweep" x1="0" y1="0" x2="1" y2="0">
            <stop offset="0" stopColor="white" stopOpacity="0" />
            <stop offset="0.5" stopColor="white" stopOpacity="0.85" />
            <stop offset="1" stopColor="white" stopOpacity="0" />
          </linearGradient>
          <clipPath id="pilot-clip">
            <path d="M32 4 58 56 32 43 6 56 32 4Z" />
          </clipPath>
        </defs>
        <path d="M32 4 58 56 32 43 6 56 32 4Z" fill="url(#pilot-glyph)" stroke="rgb(255 255 255 / 0.5)" strokeWidth="1.5" strokeLinejoin="round" />
        <g clipPath="url(#pilot-clip)">
          <rect className="pilot-sweep" x="-6" y="-8" width="26" height="80" fill="url(#pilot-sweep)" transform="skewX(-18)" />
        </g>
      </svg>
    </PilotFlight>
  );
}

const CONTAINER = "mx-auto w-full max-w-6xl px-5 sm:px-6";
const CARD =
  "group relative rounded-xl border border-border bg-card transition-colors duration-200 hover:border-border-strong hover:bg-surface-2";

export default function LandingPage() {
  return (
    <div className="landing min-h-dvh overflow-x-clip bg-background text-foreground">
      <RedirectSignedIn />
      {/* Hero and nav are always dark, in both themes, like a poster above the page. */}
      <div className="dark">
        <header className="sticky top-0 z-40 px-3 pt-3 sm:px-5 sm:pt-4">
          <div className="mx-auto flex h-14 max-w-6xl items-center justify-between rounded-full border border-white/10 bg-black/35 pl-5 pr-2 shadow-[0_10px_40px_-12px_rgb(0_0_0/0.6)] backdrop-blur-xl">
            <Link href="/" aria-label="AppPilot home" className="text-white">
              <Logo className="max-sm:hidden" />
              <Logo collapsed className="sm:hidden" />
            </Link>
            <nav className="hidden items-center gap-1 md:flex" aria-label="Sections">
              {NAV.map((n) => (
                <a
                  key={n.href}
                  href={n.href}
                  className="rounded-full px-3.5 py-1.5 text-[14px] font-medium text-white/75 transition-colors hover:bg-white/10 hover:text-white"
                >
                  {n.label}
                </a>
              ))}
            </nav>
            <div className="flex items-center gap-1.5">
              <LandingAccount />
              <ThemeToggle simple />
            </div>
          </div>
        </header>

        {/* Same charcoal-to-glow background as the Home hero and the sign-in panel. */}
        <section className="dash-hero relative isolate -mt-[4.5rem] overflow-hidden text-white">

          <div className={`${CONTAINER} pb-40 pt-36 text-center md:pb-56 md:pt-48`}>
            <p>
              <span className="inline-flex items-center gap-2 rounded-full border border-white/20 bg-white/10 px-4 py-1.5 text-[14px] font-medium text-white/90 backdrop-blur">
                <Sparkles className="size-3.5" aria-hidden /> AppPilot AI for Android teams
              </span>
            </p>
            <h1 className="mt-8 text-balance font-display text-[clamp(3rem,10vw,8.5rem)] font-semibold leading-[0.95] tracking-[-0.045em]">
              Every build,{" "}
              <span className="whitespace-nowrap">
                piloted
                <PilotGlyph className="ml-[0.08em] inline-block size-[0.72em] align-[-0.02em]" />
              </span>
            </h1>
            <p className="mx-auto mt-9 max-w-2xl text-pretty text-[17px] font-medium leading-relaxed text-white/85 md:text-xl">
              Describe an app, upload an Android Studio project or inspect an APK. AppPilot&apos;s agents plan, write, build,
              test and repair, and every edit waits for your review in a full browser IDE.
            </p>
            <div className="mt-11 flex flex-wrap items-center justify-center gap-3">
              <OpenAppButton size="lg" />
              <StartProjectButton />
            </div>
          </div>
        </section>
      </div>
      <div aria-hidden className="pointer-events-none relative -mt-48 h-48 bg-linear-to-b from-transparent to-background" />

      <main>
        <section className="relative isolate -mt-28 md:-mt-40">
          <div className={`${CONTAINER} pb-16 md:pb-24`}>
            <div className="relative">
              <HeroIllustration />
            </div>
          </div>
        </section>

        <section aria-label="Supported technologies" className="border-y border-border bg-surface/50 py-9">
          <p className="mb-6 text-center text-[13px] font-medium text-muted-foreground">
            Works with the Android stack you already use
          </p>
          <div className="relative overflow-hidden [mask-image:linear-gradient(90deg,transparent,black_12%,black_88%,transparent)]">
            <ul className="flex w-max animate-marquee gap-12 pr-12 font-display text-xl font-semibold tracking-tight text-muted-foreground/80">
              {[...TECH, ...TECH].map((t, i) => (
                <li key={i} aria-hidden={i >= TECH.length} className="whitespace-nowrap">
                  {t}
                </li>
              ))}
            </ul>
          </div>
        </section>

        <section id="start" className="relative scroll-mt-20 border-b border-border bg-surface/50">
          <div className={`${CONTAINER} py-20 md:py-28`}>
            <div className="mx-auto max-w-2xl text-center">
              <h2 className="text-balance text-3xl font-semibold tracking-[-0.03em] md:text-5xl">Three ways to start</h2>
              <p className="mt-4 text-pretty text-[16px] leading-relaxed text-muted-foreground">
                Every route ends in the same IDE, with the same agent and the same build pipeline.
              </p>
            </div>
            <div className="mt-14 grid gap-5 md:grid-cols-3">
              {ENTRY_POINTS.map((e, i) => (
                <div key={e.title} className={`${CARD} p-7`}>
                  <span className="absolute right-6 top-6 font-mono text-[13px] text-subtle-foreground">0{i + 1}</span>
                  <span className={`grid size-12 place-items-center rounded-xl ring-1 ${TONE[e.tone]}`}>
                    <e.icon className="size-5" aria-hidden />
                  </span>
                  <h3 className="mt-6 font-display text-xl font-semibold tracking-tight">{e.title}</h3>
                  <p className="mt-2.5 text-[14.5px] leading-relaxed text-muted-foreground">{e.body}</p>
                </div>
              ))}
            </div>
          </div>
        </section>

        <section id="agent" className={`${CONTAINER} scroll-mt-20 py-20 md:py-28`}>
          <div className="mx-auto max-w-2xl text-center">
            <h2 className="text-balance text-3xl font-semibold tracking-[-0.03em] md:text-5xl">The agent loop</h2>
            <p className="mt-4 text-pretty text-[16px] leading-relaxed text-muted-foreground">
              You see each stage as it happens: the file being read, the Gradle task running, the repair attempt it&apos;s
              on, and the tokens and cost it has used.
            </p>
          </div>
          <ol className="relative mt-14 grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
            <span
              aria-hidden
              className="absolute left-[10%] right-[10%] top-[2.1rem] hidden h-px bg-linear-to-r from-transparent via-ai/50 to-transparent lg:block"
            />
            {LOOP.map((s, i) => (
              <li key={s.name} className={`${CARD} overflow-hidden p-5 hover:border-ai/50 sm:max-lg:last:col-span-2`}>
                <span className="relative grid size-11 place-items-center rounded-xl bg-ai-soft text-ai ring-1 ring-ai/25">
                  <s.icon className="size-5" aria-hidden />
                  <span className="absolute -right-2 -top-2 grid size-5 place-items-center rounded-full bg-card font-mono text-[11px] font-semibold text-muted-foreground ring-1 ring-border-strong">
                    {i + 1}
                  </span>
                </span>
                <h3 className="mt-5 font-display text-lg font-semibold tracking-tight">{s.name}</h3>
                <p className="mt-1.5 text-[14px] leading-relaxed text-muted-foreground">{s.body}</p>
              </li>
            ))}
          </ol>
        </section>

        <section id="trust" className="relative scroll-mt-20 border-t border-border bg-surface/50">
          <div className={`${CONTAINER} grid gap-5 py-20 md:grid-cols-2 md:py-28`}>
            <div className={`${CARD} overflow-hidden p-9 hover:border-success/50`}>
              <div aria-hidden className="absolute -right-16 -top-16 size-56 rounded-full bg-success/15 blur-3xl" />
              <span className="relative grid size-12 place-items-center rounded-xl bg-success-soft text-success ring-1 ring-success/25">
                <CircleCheckBig className="size-5" aria-hidden />
              </span>
              <h2 className="relative mt-6 text-balance text-2xl font-semibold tracking-tight md:text-3xl">Honest results</h2>
              <p className="relative mt-3 text-[15.5px] leading-relaxed text-muted-foreground">
                A test that couldn&apos;t run isn&apos;t a pass. AppPilot reports every check as passed, failed, blocked,
                unverified or skipped, so &ldquo;green&rdquo; always means the code actually ran and met its assertions.
              </p>
            </div>
            <div className={`${CARD} overflow-hidden p-9 hover:border-ai/50`}>
              <div aria-hidden className="absolute -right-16 -top-16 size-56 rounded-full bg-ai/15 blur-3xl" />
              <span className="relative grid size-12 place-items-center rounded-xl bg-ai-soft text-ai ring-1 ring-ai/25">
                <FileDiff className="size-5" aria-hidden />
              </span>
              <h2 className="relative mt-6 text-balance text-2xl font-semibold tracking-tight md:text-3xl">
                Your code stays yours to approve
              </h2>
              <p className="relative mt-3 text-[15.5px] leading-relaxed text-muted-foreground">
                Agent changes arrive as a diff. Accept or reject each file. Lines the agent wrote stay marked in the
                editor, so you always know which code you&apos;ve reviewed.
              </p>
            </div>
          </div>
        </section>

        <section className="relative isolate overflow-hidden border-t border-border">
          <div
            aria-hidden
            className="absolute inset-0 -z-10 bg-[radial-gradient(50%_80%_at_50%_100%,color-mix(in_oklab,var(--brand-2)_28%,transparent),transparent_70%)]"
          />
          <div className={`${CONTAINER} py-20 text-center md:py-28`}>
            <h2 className="mx-auto max-w-2xl text-balance text-3xl font-semibold tracking-[-0.03em] md:text-5xl">
              Ship your next Android app with a co-pilot.
            </h2>
            <div className="mt-9 flex flex-wrap justify-center gap-3">
              <OpenAppButton size="lg" className="bg-foreground text-background shadow-none" />
            </div>
          </div>
        </section>
      </main>

      <footer className="border-t border-border">
        <div className={`${CONTAINER} flex flex-wrap items-center justify-between gap-3 py-8 text-[13px] text-muted-foreground`}>
          <Logo className="text-foreground" />
          <span>Built for Android developers.</span>
        </div>
      </footer>
    </div>
  );
}
