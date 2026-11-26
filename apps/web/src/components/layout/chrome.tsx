"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useSyncExternalStore } from "react";
import { useTheme } from "next-themes";
import { ChevronDown, FlaskConical, Globe, LogOut, Moon, Settings, ShieldHalf, Sun, UserRound, CreditCard } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Avatar, Badge } from "@/components/ui/primitives";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
  Tooltip,
} from "@/components/ui/overlays";
import { isUnauthorized } from "@/lib/api/errors";
import { IS_MOCK } from "@/lib/env";
import { useLogout, useSession } from "@/lib/api/hooks";
import { cn } from "@/lib/utils";

/** Always visible while the dev-only mock adapter is active. */
export function MockModeBadge({ className }: { className?: string }) {
  if (!IS_MOCK) return null;
  return (
    <Tooltip content="NEXT_PUBLIC_API_MODE=mock — data comes from an in-memory dev adapter, not the backend.">
      <Badge tone="warning" className={className}>
        <FlaskConical aria-hidden /> Mock data
      </Badge>
    </Tooltip>
  );
}

const noopSubscribe = () => () => {};
/** True after hydration; avoids theme-dependent markup mismatches. */
export const useMounted = () => useSyncExternalStore(noopSubscribe, () => true, () => false);

/** Toggles light/dark only; the manual choice persists via next-themes' localStorage. (`simple` is kept for existing callers.) */
// eslint-disable-next-line @typescript-eslint/no-unused-vars
export function ThemeToggle(_props: { simple?: boolean }) {
  const { resolvedTheme, setTheme } = useTheme();
  const mounted = useMounted();
  const theme = mounted ? (resolvedTheme === "dark" ? "dark" : "light") : "light";
  const next = theme === "dark" ? "light" : "dark";
  const Icon = theme === "light" ? Sun : Moon;
  return (
    <Tooltip content={`Theme: ${theme} (switch to ${next})`}>
      <Button variant="subtle" size="icon-sm" aria-label={`Switch to ${next} theme`} onClick={() => setTheme(next)}>
        <Icon />
      </Button>
    </Tooltip>
  );
}

export function UserMenu({ compact, variant = "default" }: { compact?: boolean; variant?: "default" | "sidebar" }) {
  const { data } = useSession();
  const logout = useLogout();
  const router = useRouter();
  const { resolvedTheme, setTheme } = useTheme();
  const mounted = useMounted();
  const nextTheme = mounted && resolvedTheme === "dark" ? "light" : "dark";
  const user = data?.user;
  if (!user) return null;
  const sidebar = variant === "sidebar";
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        {sidebar ? (
          <button
            className={cn(
              "flex min-w-0 items-center gap-2.5 rounded-xl border border-border-strong text-left outline-none transition-colors hover:bg-surface-3 focus-visible:ring-2 focus-visible:ring-ring data-[state=open]:bg-surface-3",
              compact ? "size-9 justify-center p-0" : "h-10 w-full pl-2 pr-2.5",
            )}
            aria-label="Account menu"
          >
            {user.avatarUrl ? (
              // eslint-disable-next-line @next/next/no-img-element -- the user's own avatar, any host
              <img src={user.avatarUrl} alt="" className="size-6 shrink-0 rounded-md object-cover" />
            ) : (
              <span aria-hidden className="grid size-6 shrink-0 place-items-center rounded-md bg-brand text-[12px] font-semibold text-white">
                {user.name.trim().charAt(0).toUpperCase() || "?"}
              </span>
            )}
            {!compact ? (
              <>
                <span className="min-w-0 flex-1 truncate text-[14px] font-semibold">{`${user.name.split(" ")[0]}'s AppPilot`}</span>
                <ChevronDown className="size-4 shrink-0 text-muted-foreground" aria-hidden />
              </>
            ) : null}
          </button>
        ) : (
          <button
            className="flex w-full min-w-0 items-center gap-2.5 rounded-lg p-1.5 text-left transition-colors hover:bg-surface-2"
            aria-label="Account menu"
          >
            <Avatar name={user.name} src={user.avatarUrl} />
            {!compact ? (
              <span className="min-w-0">
                <span className="block truncate text-[14px] font-medium">{user.name}</span>
                <span className="block truncate text-[13px] text-muted-foreground">{user.email}</span>
              </span>
            ) : null}
          </button>
        )}
      </DropdownMenuTrigger>
      <DropdownMenuContent align={sidebar ? "start" : "end"} className="w-60">
        <div className="flex items-center gap-2.5 px-2 pb-2 pt-1.5">
          <Avatar name={user.name} src={user.avatarUrl} className="size-9" />
          <div className="min-w-0">
            <p className="truncate text-[14px] font-semibold leading-tight">{user.name}</p>
            <p className="truncate text-[12.5px] text-muted-foreground">{user.email}</p>
          </div>
        </div>
        <DropdownMenuSeparator />
        <DropdownMenuItem asChild>
          <Link href="/settings?tab=account">
            <UserRound /> Profile
          </Link>
        </DropdownMenuItem>
        <DropdownMenuItem asChild>
          <Link href="/settings?tab=preferences">
            <Settings /> Account settings
          </Link>
        </DropdownMenuItem>
        <DropdownMenuItem asChild>
          <Link href="/billing">
            <CreditCard /> Billing and usage
          </Link>
        </DropdownMenuItem>
        {user.role === "admin" ? (
          <DropdownMenuItem asChild>
            <Link href="/admin">
              <ShieldHalf /> Admin
            </Link>
          </DropdownMenuItem>
        ) : null}
        <DropdownMenuSeparator />
        <DropdownMenuItem
          onSelect={(e) => {
            e.preventDefault();
            setTheme(nextTheme);
          }}
        >
          {nextTheme === "dark" ? <Moon /> : <Sun />} {nextTheme === "dark" ? "Dark mode" : "Light mode"}
        </DropdownMenuItem>
        <DropdownMenuItem asChild>
          <Link href="/">
            <Globe /> AppPilot website
          </Link>
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem
          disabled={logout.isPending}
          onSelect={(e) => {
            // Keep the menu open until the request finishes so a double click can't send it twice.
            e.preventDefault();
            logout.mutate(undefined, {
              // The server ends the session (the cookie) and the app has already dropped everything it
              // cached for this user (useLogout), so the login page is the only place left to go.
              onSuccess: () => router.replace("/login"),
              onError: (err) => {
                // A 401 means the session was already over (expired, or signed out in another tab).
                if (isUnauthorized(err)) router.replace("/login");
                else toast.error("Couldn't log out. Try again.");
              },
            });
          }}
        >
          <LogOut /> {logout.isPending ? "Logging out…" : "Log out"}
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
