import Link from "next/link";
import { Logo } from "@/components/brand/logo";
import { MockModeBadge, ThemeToggle } from "@/components/layout/chrome";
import { AuthBrandPanel } from "./auth-brand-panel";

/**
 * One shell for every auth screen (Sign in, Register, Forgot password, Reset password):
 * a calm form column on the app's own tokens, and the brand panel beside it on large screens.
 */
export function AuthShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="grid min-h-dvh bg-background text-foreground lg:grid-cols-[minmax(0,1fr)_minmax(0,1.05fr)]">
      <div className="flex min-h-dvh flex-col">
        <header className="flex h-16 items-center justify-between px-5 sm:px-8">
          <Link href="/" aria-label="AppPilot home" className="rounded-md outline-none focus-visible:ring-2 focus-visible:ring-ring">
            <Logo />
          </Link>
          <div className="flex items-center gap-2">
            <MockModeBadge />
            <ThemeToggle simple />
          </div>
        </header>
        <main className="flex flex-1 items-center justify-center px-5 pb-16 pt-4 sm:px-8">
          <div className="w-full max-w-[25rem]">{children}</div>
        </main>
      </div>
      <AuthBrandPanel />
    </div>
  );
}
