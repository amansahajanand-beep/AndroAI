"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { Dialog as DialogPrimitive } from "radix-ui";
import { FolderKanban, House, Menu, PanelLeftClose, PanelLeftOpen, Pin, Search, Settings, SquarePen, type LucideIcon } from "lucide-react";
import { Logo, LogoMark } from "@/components/brand/logo";
import { Button } from "@/components/ui/button";
import { Tooltip } from "@/components/ui/overlays";
import { useProjects } from "@/lib/api/hooks";
import { cn } from "@/lib/utils";
import { pinnedFirst, useProjectPins } from "@/stores/project-pins";
import { useUiStore } from "@/stores/ui-store";
import { MockModeBadge, UserMenu } from "./chrome";
import { UpgradeCard } from "@/features/billing/upgrade-card";
import { CommandSearch } from "./command-search";

interface NavItem {
  href: string;
  label: string;
  icon: LucideIcon;
  match?: (p: string) => boolean;
}

/** Main navigation. Billing, admin, theme and the public website live in the account menu. */
const NAV: NavItem[] = [
  { href: "/dashboard", label: "Home", icon: House },
  // Inside a project, that project's row in the list below is highlighted instead.
  { href: "/projects", label: "Projects", icon: FolderKanban, match: (p) => p === "/projects" },
  { href: "/settings", label: "Settings", icon: Settings },
];

/** One sidebar row: icon + label, rounded hover; a tooltip when collapsed. */
const ROW =
  "group relative flex h-8 w-full items-center gap-2.5 rounded-lg px-2 text-[14px] font-medium outline-none transition-colors duration-150 focus-visible:ring-2 focus-visible:ring-ring";
const ROW_IDLE = "text-foreground/85 hover:bg-surface-3 hover:text-foreground";
const ROW_ON = "bg-surface-3 text-foreground";

function WithTooltip({ collapsed, label, children }: { collapsed: boolean; label: string; children: React.ReactElement }) {
  return collapsed ? (
    <Tooltip content={label} side="right">
      {children}
    </Tooltip>
  ) : (
    children
  );
}

function SideLink({
  item,
  active,
  collapsed,
  onNavigate,
  className,
}: {
  item: NavItem;
  active: boolean;
  collapsed: boolean;
  onNavigate?: () => void;
  className?: string;
}) {
  return (
    <WithTooltip collapsed={collapsed} label={item.label}>
      <Link
        href={item.href}
        onClick={onNavigate}
        aria-current={active ? "page" : undefined}
        className={cn(ROW, active ? ROW_ON : ROW_IDLE, collapsed && "justify-center px-0", className)}
      >
        <item.icon className="size-4 shrink-0" strokeWidth={1.8} aria-hidden />
        {collapsed ? <span className="sr-only">{item.label}</span> : <span className="truncate">{item.label}</span>}
      </Link>
    </WithTooltip>
  );
}

/** Every project, newest first. It follows the projects query, so creates and deletes show up on their own. */
function ProjectList({ onNavigate }: { onNavigate?: () => void }) {
  const pathname = usePathname();
  const { data, isPending } = useProjects();
  const pinned = useProjectPins((s) => s.pinned);
  // Pinned projects first, then the newest.
  const items = pinnedFirst(
    [...(data?.items ?? [])].sort((a, b) => b.updatedAt.localeCompare(a.updatedAt)),
    pinned,
  );
  return (
    <section aria-labelledby="sidebar-projects" className="mt-6">
      <h2 id="sidebar-projects" className="mb-1 px-2 text-[13px] font-medium text-subtle-foreground">
        Projects
      </h2>
      {isPending ? (
        <div className="grid gap-2 px-2 pt-1" aria-busy="true" aria-label="Loading projects">
          {[0, 1, 2].map((i) => (
            <span key={i} className="skeleton-shimmer h-5 rounded-md bg-surface-3" />
          ))}
        </div>
      ) : items.length === 0 ? (
        <p className="px-2 py-1 text-[13px] text-subtle-foreground">No projects yet</p>
      ) : (
        <ul className="grid gap-0.5">
          {items.map((p) => {
            const active = pathname.startsWith(`/projects/${p.id}`);
            return (
              <li key={p.id}>
                <Link
                  href={`/projects/${p.id}/ide`}
                  onClick={onNavigate}
                  aria-current={active ? "page" : undefined}
                  title={p.name}
                  className={cn(ROW, "font-normal", active ? ROW_ON : ROW_IDLE)}
                >
                  <span
                    aria-hidden
                    className="grid size-[18px] shrink-0 place-items-center rounded-[5px] border border-border-strong bg-surface-2 text-[10px] font-semibold text-muted-foreground"
                  >
                    {p.name.trim().charAt(0).toUpperCase() || "?"}
                  </span>
                  <span className="min-w-0 flex-1 truncate">{p.name}</span>
                  {p.activeTaskCount > 0 ? <span className="size-1.5 shrink-0 rounded-full bg-warning" role="img" aria-label="Agent running" /> : null}
                  {pinned.includes(p.id) ? <Pin className="size-3 shrink-0 fill-current text-subtle-foreground" role="img" aria-label="Pinned" /> : null}
                </Link>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

/** Workspace switcher, navigation and the project list; shared by the desktop sidebar and the phone drawer. */
function SidebarBody({ collapsed, onNavigate, onSearch }: { collapsed: boolean; onNavigate?: () => void; onSearch: () => void }) {
  const pathname = usePathname();
  const navLink = (href: string) => {
    const item = NAV.find((n) => n.href === href);
    return item ? (
      <SideLink
        key={item.href}
        item={item}
        active={item.match ? item.match(pathname) : pathname === item.href}
        collapsed={collapsed}
        onNavigate={onNavigate}
      />
    ) : null;
  };
  return (
    <>
      <div className={cn("pb-3", collapsed && "flex justify-center")}>
        <UserMenu variant="sidebar" compact={collapsed} />
      </div>
      {/* Order: Home, Search, Projects, New project, Settings. */}
      <nav aria-label="Main" className="grid gap-0.5">
        {navLink("/dashboard")}
        <WithTooltip collapsed={collapsed} label="Search">
          <button
            type="button"
            onClick={onSearch}
            aria-keyshortcuts="Control+K Meta+K"
            className={cn(ROW, ROW_IDLE, collapsed && "justify-center px-0")}
          >
            <Search className="size-4 shrink-0" strokeWidth={1.8} aria-hidden />
            {collapsed ? (
              <span className="sr-only">Search</span>
            ) : (
              <>
                <span>Search</span>
                <kbd className="ml-auto hidden font-mono text-[11px] font-normal text-subtle-foreground group-hover:inline group-focus-visible:inline">
                  Ctrl K
                </kbd>
              </>
            )}
          </button>
        </WithTooltip>
        {navLink("/projects")}
        <SideLink
          item={{ href: "/projects/new", label: "New project", icon: SquarePen }}
          active={pathname === "/projects/new"}
          collapsed={collapsed}
          onNavigate={onNavigate}
          className={pathname === "/projects/new" ? undefined : "bg-surface-2"}
        />
        {navLink("/settings")}
      </nav>
      {collapsed ? null : <ProjectList onNavigate={onNavigate} />}
    </>
  );
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const collapsed = useUiStore((s) => s.sidebarCollapsed);
  const toggle = useUiStore((s) => s.toggleSidebar);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);

  // Ctrl/⌘+K opens search from anywhere in the app.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && !e.altKey && !e.shiftKey && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setSearchOpen((o) => !o);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const openSearch = () => {
    setMobileOpen(false);
    setSearchOpen(true);
  };

  return (
    <div className="flex min-h-dvh bg-background md:bg-(--sidebar-bg)">
      <a href="#main" className="sr-only focus:not-sr-only focus:fixed focus:left-2 focus:top-2 focus:z-50 focus:rounded-sm focus:bg-primary focus:px-3 focus:py-1.5 focus:text-primary-foreground">
        Skip to content
      </a>

      {/* Desktop sidebar: dark in both themes. */}
      <aside
        className={cn(
          "dark sticky top-0 hidden h-dvh shrink-0 flex-col bg-(--sidebar-bg) text-foreground transition-[width] duration-300 md:flex",
          collapsed ? "w-[60px]" : "w-[256px]",
        )}
      >
        <div className={cn("flex h-14 shrink-0 items-center px-4", collapsed && "justify-center px-0")}>
          <Link href="/dashboard" aria-label="AppPilot home" className="rounded-md outline-none focus-visible:ring-2 focus-visible:ring-ring">
            <LogoMark className="size-6 rounded-[7px] shadow-none" />
          </Link>
          {collapsed ? null : (
            <Tooltip content="Collapse sidebar" side="right">
              <Button variant="subtle" size="icon-sm" className="ml-auto" onClick={toggle} aria-label="Collapse sidebar">
                <PanelLeftClose />
              </Button>
            </Tooltip>
          )}
        </div>
        <div className={cn("flex-1 overflow-y-auto pb-3", collapsed ? "px-2.5" : "px-2")}>
          {collapsed ? (
            <div className="flex justify-center pb-2">
              <Tooltip content="Expand sidebar" side="right">
                <Button variant="subtle" size="icon-sm" onClick={toggle} aria-label="Expand sidebar">
                  <PanelLeftOpen />
                </Button>
              </Tooltip>
            </div>
          ) : null}
          <SidebarBody collapsed={collapsed} onSearch={openSearch} />
        </div>
        <div className={cn("shrink-0 pb-3 pt-1", collapsed ? "flex justify-center px-2.5" : "px-2")}>
          <UpgradeCard collapsed={collapsed} />
        </div>
        {collapsed ? null : <MockModeBadge className="mx-3 mb-3 self-start" />}
      </aside>

      <div className="flex min-w-0 flex-1 flex-col md:py-2 md:pr-2">
        {/* Phones and small tablets: a slim top bar opening the same sidebar as a drawer. */}
        <header className="sticky top-0 z-30 flex h-14 items-center gap-2 border-b border-border bg-background/85 px-3 backdrop-blur-xl md:hidden">
          <DialogPrimitive.Root open={mobileOpen} onOpenChange={setMobileOpen}>
            <DialogPrimitive.Trigger asChild>
              <Button variant="subtle" size="icon-sm" aria-label="Open navigation">
                <Menu />
              </Button>
            </DialogPrimitive.Trigger>
            <DialogPrimitive.Portal>
              <DialogPrimitive.Overlay className="fixed inset-0 z-50 bg-black/50 backdrop-blur-[2px]" />
              <DialogPrimitive.Content className="dark fixed inset-y-0 left-0 z-50 flex w-[280px] flex-col bg-(--sidebar-bg) px-2 text-foreground shadow-pop">
                <DialogPrimitive.Title className="flex h-14 shrink-0 items-center px-2">
                  <LogoMark className="size-6 rounded-[7px] shadow-none" />
                  <span className="sr-only">AppPilot AI</span>
                </DialogPrimitive.Title>
                <DialogPrimitive.Description className="sr-only">Main navigation</DialogPrimitive.Description>
                <div className="flex-1 overflow-y-auto pb-3">
                  <SidebarBody collapsed={false} onNavigate={() => setMobileOpen(false)} onSearch={openSearch} />
                </div>
                <div className="shrink-0 pb-3 pt-1">
                  <UpgradeCard />
                </div>
              </DialogPrimitive.Content>
            </DialogPrimitive.Portal>
          </DialogPrimitive.Root>
          <Link href="/dashboard" aria-label="AppPilot home">
            <Logo collapsed />
          </Link>
          <div className="ml-auto flex items-center gap-1">
            <MockModeBadge />
            <Button variant="subtle" size="icon-sm" onClick={openSearch} aria-label="Search">
              <Search />
            </Button>
          </div>
        </header>
        {/* Desktop: the page sits on a rounded card framed by the sidebar colour. */}
        <main
          id="main"
          className="app-ambient flex-1 bg-background md:min-h-[calc(100dvh-1rem)] md:overflow-clip md:rounded-xl md:ring-1 md:ring-white/10"
        >
          {children}
        </main>
      </div>

      <CommandSearch open={searchOpen} onOpenChange={setSearchOpen} />
    </div>
  );
}
