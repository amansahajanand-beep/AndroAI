"use client";

import { useEffect } from "react";
import { usePathname, useRouter } from "next/navigation";
import { LogoMark } from "@/components/brand/logo";
import { PendingBackend } from "@/components/states/states";
import { isPendingBackend, isUnauthorized } from "@/lib/api/errors";
import { useSession } from "@/lib/api/hooks";
import { ErrorState } from "@/components/states/states";
import { Skeleton } from "@/components/ui/primitives";

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
    // A quiet outline of the app (sidebar + page) while the session is checked, instead of a blank screen.
    return (
      <div className="flex h-dvh bg-background" aria-busy="true" aria-label="Loading">
        <div className="dark hidden w-[256px] shrink-0 flex-col gap-2 bg-(--sidebar-bg) px-3 py-4 md:flex">
          <LogoMark className="mb-3 size-6 rounded-[7px]" />
          <Skeleton className="h-10 rounded-xl" />
          <Skeleton className="mt-2 h-8 rounded-lg" />
          <Skeleton className="h-8 w-4/5 rounded-lg" />
          <Skeleton className="h-8 w-3/5 rounded-lg" />
        </div>
        <div className="flex min-w-0 flex-1 flex-col gap-4 px-6 py-10 md:px-12">
          <Skeleton className="h-7 w-48" />
          <Skeleton className="h-4 w-72 max-w-full" />
          <Skeleton className="mt-4 h-48 rounded-xl" />
        </div>
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
