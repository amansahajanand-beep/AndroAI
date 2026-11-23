"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useSyncExternalStore } from "react";
import { useTheme } from "next-themes";
import { FlaskConical, LogOut, Moon, Settings, Sun, UserRound, CreditCard } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Avatar, Badge } from "@/components/ui/primitives";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
  Tooltip,
} from "@/components/ui/overlays";
import { IS_MOCK } from "@/lib/env";
import { useLogout, useSession } from "@/lib/api/hooks";

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

export function UserMenu({ compact }: { compact?: boolean }) {
  const { data } = useSession();
  const logout = useLogout();
  const router = useRouter();
  const user = data?.user;
  if (!user) return null;
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
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
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-56">
        <DropdownMenuLabel>{user.email}</DropdownMenuLabel>
        <DropdownMenuItem asChild>
          <Link href="/settings">
            <UserRound /> Profile and settings
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
              <Settings /> Admin
            </Link>
          </DropdownMenuItem>
        ) : null}
        <DropdownMenuSeparator />
        <DropdownMenuItem
          onSelect={() =>
            logout.mutate(undefined, {
              onSuccess: () => router.replace("/login"),
              onError: () => toast.error("Couldn't sign out. Try again."),
            })
          }
        >
          <LogOut /> Sign out
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
