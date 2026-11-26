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
  "inline-flex items-center justify-center gap-1.5 whitespace-nowrap rounded-full bg-white font-medium text-[#0b0a1a] transition-colors duration-150 hover:bg-white/85 active:scale-[0.98]";

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

/** Guests see Sign in and Sign up; signed-in users see their avatar and account menu. */
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
  // Signed out: both options on every screen size (phones included).
  return (
    <>
      <Link href="/login" className="inline-flex h-10 items-center rounded-full px-3.5 text-[14px] font-medium text-white/80 transition-colors hover:text-white sm:px-4">
        Sign in
      </Link>
      <Link href="/register" className={cn(PILL, "h-9 px-4 text-[14px]")}>
        Sign up
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
