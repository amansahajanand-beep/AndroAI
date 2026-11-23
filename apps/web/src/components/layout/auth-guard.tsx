"use client";

import { useEffect } from "react";
import { usePathname, useRouter } from "next/navigation";
import { LogoMark } from "@/components/brand/logo";
import { PendingBackend } from "@/components/states/states";
import { isPendingBackend, isUnauthorized } from "@/lib/api/errors";
import { useSession } from "@/lib/api/hooks";
import { ErrorState } from "@/components/states/states";

/**
 * Client-side session gate for the signed-in app. The backend remains the
 * authority: every API call is still checked server-side.
 */
export function AuthGuard({ children, requireAdmin }: { children: React.ReactNode; requireAdmin?: boolean }) {
  const session = useSession();
  const router = useRouter();
  const pathname = usePathname();
  const unauthorized = session.isError && isUnauthorized(session.error);

  useEffect(() => {
    if (unauthorized) router.replace(`/login?next=${encodeURIComponent(pathname)}`);
  }, [unauthorized, pathname, router]);

  if (session.isPending || unauthorized) {
    return (
      <div className="grid h-dvh place-items-center" aria-busy="true">
        <LogoMark className="size-8 animate-pulse text-muted-foreground" />
      </div>
    );
  }
  if (session.isError) {
    return (
      <div className="grid h-dvh place-items-center">
        {isPendingBackend(session.error) ? (
          <PendingBackend endpoint="auth.session">
            The sign-in API isn&apos;t reachable. To work on the UI without a backend, run{" "}
            <code>npm run dev:web:mock</code>.
          </PendingBackend>
        ) : (
          <ErrorState error={session.error} onRetry={() => session.refetch()} />
        )}
      </div>
    );
  }
  if (requireAdmin && session.data.user.role !== "admin") {
    return (
      <div className="grid h-dvh place-items-center text-center">
        <div>
          <p className="font-medium">Admins only</p>
          <p className="mt-1 text-[14px] text-muted-foreground">Your account doesn&apos;t have access to this page.</p>
        </div>
      </div>
    );
  }
  return <>{children}</>;
}
