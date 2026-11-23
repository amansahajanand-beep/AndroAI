import Link from "next/link";
import { Logo } from "@/components/brand/logo";
import { MockModeBadge, ThemeToggle } from "@/components/layout/chrome";
import { AuthBrandPanel } from "@/features/auth/auth-brand-panel";

/** Shell for Sign in and Register. Forgot/Reset password keep the plain `(auth)` layout. */
export default function AccessLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="auth-surface grid min-h-dvh bg-background text-foreground lg:grid-cols-[minmax(0,1fr)_minmax(0,1.05fr)]">
      <div className="relative isolate flex min-h-dvh flex-col overflow-hidden">
        <div
          aria-hidden
          className="pointer-events-none absolute inset-x-0 top-0 -z-10 h-72 bg-[radial-gradient(60%_100%_at_50%_0%,color-mix(in_oklab,var(--brand-2)_25%,transparent),transparent_75%)] lg:hidden"
        />
        <header className="flex h-16 items-center justify-between px-5 sm:px-8">
          <Link href="/" aria-label="AppPilot home">
            <Logo />
          </Link>
          <div className="flex items-center gap-2">
            <MockModeBadge />
            <ThemeToggle simple />
          </div>
        </header>
        <main className="flex flex-1 items-center justify-center px-5 pb-16 pt-4 sm:px-8">
          <div className="w-full max-w-[26rem] animate-fade-up">{children}</div>
        </main>
      </div>
      <AuthBrandPanel />
    </div>
  );
}
