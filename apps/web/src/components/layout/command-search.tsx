"use client";

import { useRouter } from "next/navigation";
import { useId, useState } from "react";
import { CornerDownLeft, CreditCard, FolderKanban, House, Search, Settings, ShieldHalf, SquarePen, type LucideIcon } from "lucide-react";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/overlays";
import { useProjects, useSession } from "@/lib/api/hooks";
import { cn } from "@/lib/utils";

interface Item {
  key: string;
  label: string;
  hint?: string;
  href: string;
  icon?: LucideIcon;
  initial?: string;
}

const PAGES: (Item & { admin?: boolean })[] = [
  { key: "p:home", label: "Home", href: "/dashboard", icon: House },
  { key: "p:new", label: "New project", href: "/projects/new", icon: SquarePen },
  { key: "p:projects", label: "Projects", href: "/projects", icon: FolderKanban },
  { key: "p:settings", label: "Settings", href: "/settings", icon: Settings },
  { key: "p:billing", label: "Billing and usage", href: "/billing", icon: CreditCard },
  { key: "p:admin", label: "Admin", href: "/admin", icon: ShieldHalf, admin: true },
];

/** Projects shown before anything is typed. */
const RECENT = 6;

/**
 * Sidebar search (Ctrl/⌘+K): jump to any project or app page.
 * Searches the projects list already loaded by the app; no new API.
 */
export function CommandSearch({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="top-[14%] max-w-xl translate-y-0 gap-0 overflow-hidden p-0">
        <DialogTitle className="sr-only">Search</DialogTitle>
        <DialogDescription className="sr-only">Find a project or a page. Use the arrow keys and Enter to open it.</DialogDescription>
        {/* Mounted only while open, so every search starts fresh. */}
        <SearchBody onClose={() => onOpenChange(false)} />
      </DialogContent>
    </Dialog>
  );
}

function SearchBody({ onClose }: { onClose: () => void }) {
  const router = useRouter();
  const projects = useProjects();
  const { data: session } = useSession();
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const listId = useId();

  const q = query.trim().toLowerCase();
  const all = [...(projects.data?.items ?? [])].sort((a, b) => b.updatedAt.localeCompare(a.updatedAt));
  const projectItems: Item[] = (q
    ? all.filter((p) => [p.name, p.description, p.packageName].some((f) => f?.toLowerCase().includes(q)))
    : all.slice(0, RECENT)
  ).map((p) => ({
    key: `project:${p.id}`,
    label: p.name,
    hint: p.packageName ?? undefined,
    href: `/projects/${p.id}/ide`,
    initial: p.name.trim().charAt(0).toUpperCase() || "?",
  }));
  const pageItems: Item[] = PAGES.filter((p) => (!p.admin || session?.user.role === "admin") && (!q || p.label.toLowerCase().includes(q)));
  const groups = [
    { label: q ? "Projects" : "Recent projects", items: projectItems },
    { label: "Pages", items: pageItems },
  ].filter((g) => g.items.length > 0);
  const flat = groups.flatMap((g) => g.items);
  const current = Math.min(active, Math.max(flat.length - 1, 0));

  const go = (item: Item | undefined) => {
    if (!item) return;
    onClose();
    router.push(item.href);
  };

  return (
    <>
        <div className="flex items-center gap-2.5 border-b border-border px-4">
          <Search className="size-4 shrink-0 text-muted-foreground" aria-hidden />
          <input
            autoFocus
            role="combobox"
            aria-expanded="true"
            aria-controls={listId}
            aria-activedescendant={flat[current] ? `${listId}-${current}` : undefined}
            aria-label="Search projects and pages"
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setActive(0);
            }}
            onKeyDown={(e) => {
              if (e.key === "ArrowDown") {
                e.preventDefault();
                setActive((current + 1) % Math.max(flat.length, 1));
              } else if (e.key === "ArrowUp") {
                e.preventDefault();
                setActive((current - 1 + flat.length) % Math.max(flat.length, 1));
              } else if (e.key === "Enter") {
                e.preventDefault();
                go(flat[current]);
              }
            }}
            placeholder="Search projects and pages…"
            className="h-12 w-full bg-transparent pr-8 text-[15px] text-foreground outline-none placeholder:text-subtle-foreground"
          />
        </div>
        <div id={listId} role="listbox" aria-label="Results" className="max-h-[min(60vh,420px)] overflow-y-auto p-1.5">
          {flat.length === 0 ? (
            <p className="px-3 py-8 text-center text-[14px] text-muted-foreground">
              {projects.isPending ? "Loading projects…" : <>Nothing matches &ldquo;{query.trim()}&rdquo;.</>}
            </p>
          ) : (
            groups.map((g) => (
              <div key={g.label} role="group" aria-label={g.label} className="pb-1">
                <p className="px-2.5 pb-1 pt-2 text-[12px] font-medium text-subtle-foreground">{g.label}</p>
                {g.items.map((item) => {
                  const index = flat.indexOf(item);
                  const selected = index === current;
                  return (
                    <div
                      key={item.key}
                      id={`${listId}-${index}`}
                      role="option"
                      aria-selected={selected}
                      onMouseMove={() => setActive(index)}
                      onClick={() => go(item)}
                      className={cn(
                        "flex h-9 cursor-pointer items-center gap-2.5 rounded-md px-2.5 text-[14px]",
                        selected ? "bg-surface-3 text-foreground" : "text-foreground/85",
                      )}
                    >
                      {item.icon ? (
                        <item.icon className="size-4 shrink-0 text-muted-foreground" aria-hidden />
                      ) : (
                        <span aria-hidden className="grid size-[18px] shrink-0 place-items-center rounded-[5px] border border-border-strong text-[10px] font-semibold text-muted-foreground">
                          {item.initial}
                        </span>
                      )}
                      <span className="truncate">{item.label}</span>
                      {item.hint ? <span className="hidden truncate font-mono text-[12px] text-subtle-foreground sm:inline">{item.hint}</span> : null}
                      {selected ? <CornerDownLeft className="ml-auto size-3.5 shrink-0 text-subtle-foreground" aria-hidden /> : null}
                    </div>
                  );
                })}
              </div>
            ))
          )}
        </div>
    </>
  );
}
