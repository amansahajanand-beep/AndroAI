"use client";

import Link from "next/link";
import { ArrowUpRight } from "lucide-react";
import { useSession } from "@/lib/api/hooks";
import { isUnauthorized } from "@/lib/api/errors";
import { UserMenu } from "@/components/layout/chrome";
import { cn } from "@/lib/utils";

/** Where an "enter the app" click should go, from the existing session query. */
export function useAppEntry() {
  const session = useSession();
  const signedIn = !!session.data;
  const guest = session.isError && (isUnauthorized(session.error) || !session.data);
  // While the session is still loading we point at the app: AuthGuard sends guests to /login.
  const href = guest ? "/login" : "/dashboard";
  return { signedIn, guest, href, loading: session.isPending };
}

const PILL =
  "inline-flex items-center justify-center gap-1.5 whitespace-nowrap rounded-full bg-white font-medium text-[#0b0a1a] shadow-[0_8px_30px_-8px_rgb(255_255_255/0.45)] transition-all duration-200 hover:scale-[1.03] hover:shadow-[0_10px_36px_-6px_rgb(255_255_255/0.6)] active:scale-[0.97]";

/** Primary entry into the application from the marketing site. */
export function OpenAppButton({ size = "md", className }: { size?: "md" | "lg"; className?: string }) {
  const { href } = useAppEntry();
  return (
    <Link href={href} className={cn(PILL, size === "lg" ? "h-12 px-7 text-[15px]" : "h-10 px-4 text-[14px] sm:px-5", className)}>
      Open AppPilot
      <ArrowUpRight className="size-4" aria-hidden />
    </Link>
  );
}

/** Guests see Sign in / Create account; signed-in users see their account menu. */
export function LandingAccount() {
  const { signedIn, loading } = useAppEntry();
  if (signedIn) {
    return (
      <div>
        <UserMenu compact />
      </div>
    );
  }
  if (loading) return null;
  return (
    <>
      <Link href="/login" className="hidden h-10 items-center rounded-full px-4 text-[14px] font-medium text-white/80 transition-colors hover:text-white sm:inline-flex">
        Sign in
      </Link>
      <Link href="/register" className="hidden h-10 items-center rounded-full px-4 text-[14px] font-medium text-white/80 transition-colors hover:text-white md:inline-flex">
        Create account
      </Link>
    </>
  );
}

/** Secondary hero CTA: start a project (signed in) or create an account (guest). */
export function StartProjectButton({ className }: { className?: string }) {
  const { signedIn } = useAppEntry();
  return (
    <Link
      href={signedIn ? "/projects/new" : "/register"}
      className={cn(
        "inline-flex h-12 items-center justify-center gap-1.5 rounded-full border border-white/25 bg-white/10 px-7 text-[15px] font-medium text-white backdrop-blur transition-all duration-200 hover:border-white/50 hover:bg-white/20 active:scale-[0.97]",
        className,
      )}
    >
      {signedIn ? "Start a project" : "Create free account"}
    </Link>
  );
}
