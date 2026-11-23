"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";
import { Dialog as DialogPrimitive } from "radix-ui";
import {
  CreditCard,
  FolderKanban,
  LayoutDashboard,
  Menu,
  PanelLeftClose,
  PanelLeftOpen,
  Globe,
  Plus,
  Settings,
  ShieldHalf,
  type LucideIcon,
} from "lucide-react";
import { Logo } from "@/components/brand/logo";
import { Button } from "@/components/ui/button";
import { Tooltip } from "@/components/ui/overlays";
import { useSession } from "@/lib/api/hooks";
import { cn } from "@/lib/utils";
import { useUiStore } from "@/stores/ui-store";
import { MockModeBadge, ThemeToggle, UserMenu } from "./chrome";

interface NavItem {
  href: string;
  label: string;
  icon: LucideIcon;
  admin?: boolean;
  match?: (p: string) => boolean;
}

const NAV: NavItem[] = [
  { href: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
  { href: "/projects", label: "Projects", icon: FolderKanban, match: (p) => p.startsWith("/projects") },
  { href: "/billing", label: "Billing and usage", icon: CreditCard },
  { href: "/settings", label: "Settings", icon: Settings },
  { href: "/admin", label: "Admin", icon: ShieldHalf, admin: true },
];

function NavLinks({ collapsed, onNavigate }: { collapsed: boolean; onNavigate?: () => void }) {
  const pathname = usePathname();
  const { data } = useSession();
  const isAdmin = data?.user.role === "admin";
  return (
    <nav aria-label="Main" className="grid gap-1">
      {NAV.filter((n) => !n.admin || isAdmin).map((item) => {
        const active = item.match ? item.match(pathname) : pathname === item.href;
        const link = (
          <Link
            key={item.href}
            href={item.href}
            onClick={onNavigate}
            aria-current={active ? "page" : undefined}
            className={cn(
              "group relative flex h-9 items-center gap-2.5 rounded-sm px-2.5 text-[14px] font-medium transition-all duration-200",
              active
                ? "bg-primary-soft text-foreground ring-1 ring-primary/25"
                : "text-muted-foreground hover:bg-surface-2 hover:text-foreground",
              collapsed && "justify-center px-0",
            )}
          >
            {active ? <span aria-hidden className="absolute left-0 top-2 bottom-2 w-[3px] rounded-full bg-brand" /> : null}
            <item.icon className={cn("size-4 shrink-0 transition-colors", active ? "text-primary" : "group-hover:text-primary")} aria-hidden />
            {collapsed ? <span className="sr-only">{item.label}</span> : item.label}
          </Link>
        );
        return collapsed ? (
          <Tooltip key={item.href} content={item.label} side="right">
            {link}
          </Tooltip>
        ) : (
          link
        );
      })}
    </nav>
  );
}

/** Back to the public marketing site; keeps app and website one click apart. */
function WebsiteLink({ collapsed, onNavigate }: { collapsed: boolean; onNavigate?: () => void }) {
  const link = (
    <Link
      href="/"
      onClick={onNavigate}
      className={cn(
        "mt-4 flex h-9 items-center gap-2.5 rounded-sm border border-dashed border-border-strong px-2.5 text-[13px] text-muted-foreground transition-colors hover:border-primary/50 hover:text-foreground",
        collapsed && "justify-center px-0",
      )}
    >
      <Globe className="size-4 shrink-0" aria-hidden />
      {collapsed ? <span className="sr-only">AppPilot website</span> : "AppPilot website"}
    </Link>
  );
  return collapsed ? (
    <Tooltip content="AppPilot website" side="right">
      {link}
    </Tooltip>
  ) : (
    link
  );
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const collapsed = useUiStore((s) => s.sidebarCollapsed);
  const toggle = useUiStore((s) => s.toggleSidebar);
  const [mobileOpen, setMobileOpen] = useState(false);

  return (
    <div className="flex min-h-dvh">
      <a href="#main" className="sr-only focus:not-sr-only focus:fixed focus:left-2 focus:top-2 focus:z-50 focus:rounded-sm focus:bg-primary focus:px-3 focus:py-1.5 focus:text-primary-foreground">
        Skip to content
      </a>

      {/* Desktop sidebar */}
      <aside
        className={cn(
          "sticky top-0 hidden h-dvh shrink-0 flex-col border-r border-border bg-surface/80 backdrop-blur-xl transition-[width] duration-300 md:flex",
          collapsed ? "w-[68px]" : "w-64",
        )}
      >
        <div className={cn("flex h-16 items-center px-4", collapsed && "justify-center px-0")}>
          <Link href="/dashboard" aria-label="AppPilot home">
            <Logo collapsed={collapsed} />
          </Link>
        </div>
        <div className="flex-1 overflow-y-auto px-3 pb-3">
          <Button asChild className={cn("mb-5 w-full", collapsed && "px-0")}>
            <Link href="/projects/new" aria-label="New project">
              <Plus />
              {collapsed ? null : "New project"}
            </Link>
          </Button>
          <NavLinks collapsed={collapsed} />
          <WebsiteLink collapsed={collapsed} />
        </div>
        <div className={cn("border-t border-border p-3", collapsed && "flex flex-col items-center gap-1")}>
          <UserMenu compact={collapsed} />
          <Tooltip content={collapsed ? "Expand sidebar" : "Collapse sidebar"} side="right">
            <Button variant="subtle" size="icon-sm" className={cn(!collapsed && "mt-1")} onClick={toggle} aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}>
              {collapsed ? <PanelLeftOpen /> : <PanelLeftClose />}
            </Button>
          </Tooltip>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-30 flex h-14 items-center gap-2 border-b border-border/70 bg-background/70 px-3 backdrop-blur-xl md:px-5">
          <DialogPrimitive.Root open={mobileOpen} onOpenChange={setMobileOpen}>
            <DialogPrimitive.Trigger asChild>
              <Button variant="subtle" size="icon-sm" className="md:hidden" aria-label="Open navigation">
                <Menu />
              </Button>
            </DialogPrimitive.Trigger>
            <DialogPrimitive.Portal>
              <DialogPrimitive.Overlay className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm" />
              <DialogPrimitive.Content className="fixed inset-y-0 left-0 z-50 flex w-72 flex-col border-r border-border bg-surface p-4 shadow-pop">
                <DialogPrimitive.Title className="mb-3">
                  <Logo />
                </DialogPrimitive.Title>
                <DialogPrimitive.Description className="sr-only">Main navigation</DialogPrimitive.Description>
                <NavLinks collapsed={false} onNavigate={() => setMobileOpen(false)} />
                <WebsiteLink collapsed={false} onNavigate={() => setMobileOpen(false)} />
                <div className="mt-auto border-t border-border pt-2">
                  <UserMenu />
                </div>
              </DialogPrimitive.Content>
            </DialogPrimitive.Portal>
          </DialogPrimitive.Root>
          <Link href="/dashboard" className="md:hidden" aria-label="AppPilot home">
            <Logo collapsed />
          </Link>
          <div className="ml-auto flex items-center gap-2">
            <MockModeBadge />
            <ThemeToggle />
          </div>
        </header>
        <main id="main" className="app-ambient flex-1">
          {children}
        </main>
      </div>
    </div>
  );
}
