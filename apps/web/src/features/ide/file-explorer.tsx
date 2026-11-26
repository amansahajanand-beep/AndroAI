"use client";

import { forwardRef, useEffect, useImperativeHandle, useMemo, useRef, useState } from "react";
import type { FileNode, FileSearchResult, GitFileStatus } from "@apppilot/contracts";
import {
  ChevronRight,
  ChevronsDownUp,
  Copy,
  File as FileIcon,
  FileCode,
  FileCode2,
  FileCog,
  FileImage,
  FileJson,
  FileText,
  FilePlus2,
  Folder,
  FolderOpen,
  FolderPlus,
  Pencil,
  RefreshCw,
  Search,
  Sparkles,
  Trash2,
  X,
  type LucideIcon,
} from "lucide-react";
import { toast } from "sonner";
import { ErrorState, LoadingRows, EmptyState } from "@/components/states/states";
import { Button } from "@/components/ui/button";
import { ConfirmDialog, ContextMenu, ContextMenuContent, ContextMenuItem, ContextMenuSeparator, ContextMenuTrigger, Tooltip } from "@/components/ui/overlays";
import { Input } from "@/components/ui/primitives";
import { errorMessage } from "@/lib/api/errors";
import { useFileMutations, useFileSearch, useFileTree } from "@/lib/api/hooks";
import { basename, cn, dirname } from "@/lib/utils";
import { useDirtyPaths, useIdeStore } from "@/stores/ide-store";

const GIT_MARK: Record<GitFileStatus, { letter: string; className: string; label: string }> = {
  modified: { letter: "M", className: "text-git-modified", label: "Modified" },
  added: { letter: "A", className: "text-git-added", label: "Added" },
  deleted: { letter: "D", className: "text-git-deleted", label: "Deleted" },
  untracked: { letter: "U", className: "text-git-untracked", label: "Untracked" },
};

/** File-type icon and colour, so a tree full of files scans at a glance. */
const FILE_KIND: { test: RegExp; icon: LucideIcon; color: string }[] = [
  { test: /\.(kts?|kt)$/i, icon: FileCode2, color: "text-[#6d4fe0] dark:text-[#a99bff]" },
  { test: /\.java$/i, icon: FileCode2, color: "text-[#b9600f] dark:text-[#f0a35e]" },
  { test: /(\.gradle|gradle\.kts|gradlew(\.bat)?)$/i, icon: FileCog, color: "text-[#2a8048] dark:text-[#8fd19e]" },
  { test: /\.xml$/i, icon: FileCode, color: "text-[#c2571f] dark:text-[#f59e6b]" },
  { test: /\.json$/i, icon: FileJson, color: "text-[#9a7300] dark:text-[#f0c36e]" },
  { test: /\.(md|txt)$/i, icon: FileText, color: "text-[#2c68cf] dark:text-[#7fb2ff]" },
  { test: /\.(png|jpe?g|webp|gif|svg)$/i, icon: FileImage, color: "text-[#bd3577] dark:text-[#f28cb8]" },
  { test: /\.(properties|pro|toml|ya?ml|cfg)$/i, icon: FileCog, color: "text-muted-foreground" },
];
function fileKind(name: string) {
  return FILE_KIND.find((k) => k.test.test(name)) ?? { icon: FileIcon, color: "text-subtle-foreground" };
}

function countFiles(nodes: FileNode[]): number {
  return nodes.reduce((n, x) => n + (x.type === "file" ? 1 : countFiles(x.children ?? [])), 0);
}

const INVALID_NAME = /[\\:*?"<>|]|^\.\.?$|\/\/|^\/|\/$/;

type Draft = { kind: "create"; parent: string; type: "file" | "dir" } | { kind: "rename"; path: string };

function filterTree(nodes: FileNode[], needle: string): FileNode[] {
  if (!needle) return nodes;
  const out: FileNode[] = [];
  for (const n of nodes) {
    if (n.type === "dir") {
      const kids = filterTree(n.children ?? [], needle);
      if (kids.length || n.name.toLowerCase().includes(needle)) out.push({ ...n, children: kids.length ? kids : n.children });
    } else if (n.name.toLowerCase().includes(needle)) out.push(n);
  }
  return out;
}

/** Bubble git/AI state up to folders so collapsed folders still show changes. */
function folderMarks(nodes: FileNode[]) {
  const ai = new Set<string>();
  const changed = new Set<string>();
  const walk = (n: FileNode): { ai: boolean; changed: boolean } => {
    if (n.type === "file") return { ai: !!n.aiModified, changed: !!n.gitStatus };
    let a = false;
    let c = false;
    for (const k of n.children ?? []) {
      const r = walk(k);
      a ||= r.ai;
      c ||= r.changed;
    }
    if (a) ai.add(n.path);
    if (c) changed.add(n.path);
    return { ai: a, changed: c };
  };
  nodes.forEach(walk);
  return { ai, changed };
}

function DraftInput({ initial, depth, icon, onSubmit, onCancel }: { initial: string; depth: number; icon: React.ReactNode; onSubmit: (v: string) => void; onCancel: () => void }) {
  const [value, setValue] = useState(initial);
  const [error, setError] = useState<string>();
  const ref = useRef<HTMLInputElement>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.focus();
    const dot = initial.lastIndexOf(".");
    el.setSelectionRange(0, dot > 0 ? dot : initial.length);
  }, [initial]);
  return (
    <div className="py-0.5 pr-2" style={{ paddingLeft: 8 + depth * 12 }}>
      <div className="flex items-center gap-1.5">
        {icon}
        <Input
          ref={ref}
          value={value}
          aria-label="Name"
          aria-invalid={!!error}
          className="h-6 px-1.5 font-mono text-[13px]"
          onChange={(e) => {
            setValue(e.target.value);
            setError(undefined);
          }}
          onKeyDown={(e) => {
            if (e.key === "Escape") onCancel();
            if (e.key === "Enter") {
              const v = value.trim();
              if (!v) return onCancel();
              if (INVALID_NAME.test(v)) return setError("Names can't contain \\ : * ? \" < > | or start/end with /");
              onSubmit(v);
            }
          }}
          onBlur={onCancel}
        />
      </div>
      {error ? <p className="mt-0.5 pl-5 text-[12px] text-destructive">{error}</p> : null}
    </div>
  );
}

/** Drag payload type for moving files and folders inside the explorer (ignores OS file drops and text). */
const DRAG_MIME = "application/x-apppilot-path";

export interface FileExplorerHandle {
  focusSearch: (mode?: "names" | "content") => void;
}

export const FileExplorer = forwardRef<FileExplorerHandle, { projectId: string; readOnly?: boolean }>(function FileExplorer({ projectId, readOnly }, ref) {
  const tree = useFileTree(projectId);
  const { create, move, remove } = useFileMutations(projectId);
  const openFile = useIdeStore((s) => s.openFile);
  const renamePath = useIdeStore((s) => s.renamePath);
  const removePath = useIdeStore((s) => s.removePath);
  const active = useIdeStore((s) => s.tabs[projectId]?.active ?? null);
  const dirty = new Set(useDirtyPaths(projectId));
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set(active ? ancestors(active) : []));
  const [query, setQuery] = useState("");
  const [mode, setMode] = useState<"names" | "content">("names");
  const [draft, setDraft] = useState<Draft | null>(null);
  const [toDelete, setToDelete] = useState<FileNode | null>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  const content = useFileSearch(projectId, mode === "content" ? query : "");

  useImperativeHandle(ref, () => ({
    focusSearch: (m) => {
      if (m) setMode(m);
      searchRef.current?.focus();
    },
  }));

  // Reveal the active file in the tree.
  const lastRevealed = useRef<string | null>(null);
  useEffect(() => {
    if (active && active !== lastRevealed.current && !active.startsWith("review:")) {
      lastRevealed.current = active;
      setExpanded((s) => new Set([...s, ...ancestors(active)]));
    }
  }, [active]);

  const needle = mode === "names" ? query.trim().toLowerCase() : "";
  const nodes = useMemo(() => filterTree(tree.data ?? [], needle), [tree.data, needle]);
  const marks = useMemo(() => folderMarks(tree.data ?? []), [tree.data]);

  /* ---------- Drag and drop: move files and folders ---------- */
  const [dragging, setDragging] = useState<string | null>(null);
  /** Folder the dragged item would land in; "" is the project root, null means no valid target. */
  const [dropTarget, setDropTarget] = useState<string | null>(null);
  const hoverExpand = useRef<{ path: string; timer: ReturnType<typeof setTimeout> } | null>(null);
  const allPaths = useMemo(() => {
    const set = new Set<string>();
    const walk = (list: FileNode[]) => list.forEach((n) => { set.add(n.path); if (n.children) walk(n.children); });
    walk(tree.data ?? []);
    return set;
  }, [tree.data]);
  const canDrag = !readOnly && !draft;
  /** Not where it already is, and never into itself or one of its own subfolders. */
  const isValidTarget = (from: string, toDir: string) => dirname(from) !== toDir && toDir !== from && !toDir.startsWith(`${from}/`);
  const clearHoverExpand = () => {
    if (hoverExpand.current) clearTimeout(hoverExpand.current.timer);
    hoverExpand.current = null;
  };
  const endDrag = () => {
    setDragging(null);
    setDropTarget(null);
    clearHoverExpand();
  };
  const moveInto = (from: string, toDir: string) => {
    if (!isValidTarget(from, toDir)) return;
    const name = basename(from);
    const to = toDir ? `${toDir}/${name}` : name;
    const where = toDir || "the project root";
    if (allPaths.has(to)) {
      toast.error(`${name} already exists in ${where}.`);
      return;
    }
    move.mutate(
      { from, to },
      {
        onSuccess: () => {
          renamePath(projectId, from, to); // keeps open tabs and unsaved edits pointing at the new path
          if (toDir) setExpanded((s) => new Set([...s, toDir]));
          toast.success(`Moved ${name} to ${where}`);
        },
        onError: (e) => toast.error(errorMessage(e)),
      },
    );
  };
  /** Handles dragover for a target folder. Returns true when a drop would be accepted. */
  const dragOverFolder = (e: React.DragEvent, toDir: string) => {
    if (!dragging || !e.dataTransfer.types.includes(DRAG_MIME)) return false;
    e.preventDefault();
    e.stopPropagation();
    const ok = isValidTarget(dragging, toDir);
    e.dataTransfer.dropEffect = ok ? "move" : "none";
    setDropTarget(ok ? toDir : null);
    return ok;
  };
  const dropOnFolder = (e: React.DragEvent, toDir: string) => {
    if (!e.dataTransfer.types.includes(DRAG_MIME)) return;
    e.preventDefault();
    e.stopPropagation();
    const from = e.dataTransfer.getData(DRAG_MIME) || dragging;
    endDrag();
    if (from) moveInto(from, toDir);
  };
  useEffect(() => clearHoverExpand, []);

  const toggle = (p: string) =>
    setExpanded((s) => {
      const n = new Set(s);
      if (n.has(p)) n.delete(p);
      else n.add(p);
      return n;
    });

  const submitDraft = (value: string) => {
    if (!draft) return;
    if (draft.kind === "create") {
      const path = draft.parent ? `${draft.parent}/${value}` : value;
      create.mutate(
        { path, type: draft.type, content: "" },
        {
          onSuccess: () => {
            if (draft.type === "file") openFile(projectId, path);
            else setExpanded((s) => new Set([...s, path]));
          },
          onError: (e) => toast.error(errorMessage(e)),
        },
      );
    } else {
      const to = dirname(draft.path) ? `${dirname(draft.path)}/${value}` : value;
      if (to !== draft.path)
        move.mutate(
          { from: draft.path, to },
          { onSuccess: () => renamePath(projectId, draft.path, to), onError: (e) => toast.error(errorMessage(e)) },
        );
    }
    setDraft(null);
  };

  const startCreate = (type: "file" | "dir", parent: string) => {
    if (parent) setExpanded((s) => new Set([...s, parent]));
    setDraft({ kind: "create", parent, type });
  };

  const renderNodes = (list: FileNode[], depth: number, parent: string): React.ReactNode => (
    <>
      {draft?.kind === "create" && draft.parent === parent ? (
        <DraftInput
          initial=""
          depth={depth}
          icon={draft.type === "dir" ? <Folder className="size-3.5 shrink-0 text-muted-foreground" /> : <FileCode2 className="size-3.5 shrink-0 text-muted-foreground" />}
          onSubmit={submitDraft}
          onCancel={() => setDraft(null)}
        />
      ) : null}
      {list.map((n) => {
        if (draft?.kind === "rename" && draft.path === n.path)
          return <DraftInput key={n.path} initial={n.name} depth={depth} icon={<Pencil className="size-3.5 shrink-0 text-muted-foreground" />} onSubmit={submitDraft} onCancel={() => setDraft(null)} />;
        const isDir = n.type === "dir";
        const open = isDir && (expanded.has(n.path) || !!needle);
        const git = n.gitStatus ? GIT_MARK[n.gitStatus] : null;
        const ai = isDir ? marks.ai.has(n.path) : n.aiModified;
        const isDirty = dirty.has(n.path);
        const Kind = fileKind(n.name);
        return (
          <li
            key={n.path}
            role="treeitem"
            aria-expanded={isDir ? open : undefined}
            aria-selected={active === n.path}
            draggable={canDrag}
            onDragStart={(e) => {
              e.stopPropagation();
              if (!canDrag) return e.preventDefault();
              e.dataTransfer.setData(DRAG_MIME, n.path);
              e.dataTransfer.effectAllowed = "move";
              // Drag image: just this row, not the whole expanded subtree.
              const row = (e.currentTarget as HTMLElement).querySelector("button");
              if (row) e.dataTransfer.setDragImage(row, 16, 14);
              setDragging(n.path);
            }}
            onDragEnd={endDrag}
          >
            <ContextMenu>
              <ContextMenuTrigger asChild>
                <button
                  className={cn(
                    "group mx-1.5 flex h-7 w-[calc(100%-0.75rem)] items-center gap-1.5 rounded-md pr-2 text-left text-[13px] text-foreground/85 transition-colors hover:bg-surface-3/70 hover:text-foreground focus-visible:outline-offset-[-2px]",
                    active === n.path &&
                      "relative bg-surface-3 text-foreground before:absolute before:inset-y-1.5 before:left-0 before:w-0.5 before:rounded-full before:bg-primary",
                    dragging === n.path && "opacity-50",
                    isDir && dropTarget === n.path && "bg-primary-soft text-foreground ring-1 ring-inset ring-primary/40",
                  )}
                  style={{ paddingLeft: 8 + depth * 12 }}
                  onClick={() => (isDir ? toggle(n.path) : openFile(projectId, n.path))}
                  onDragOver={(e) => {
                    // Dropping on a file means "next to it", i.e. into that file's folder.
                    const ok = dragOverFolder(e, isDir ? n.path : dirname(n.path));
                    if (ok && isDir && !open) {
                      if (hoverExpand.current?.path !== n.path) {
                        clearHoverExpand();
                        hoverExpand.current = { path: n.path, timer: setTimeout(() => setExpanded((s) => new Set([...s, n.path])), 650) };
                      }
                    } else if (hoverExpand.current && hoverExpand.current.path !== n.path) clearHoverExpand();
                  }}
                  onDrop={(e) => dropOnFolder(e, isDir ? n.path : dirname(n.path))}
                  title={n.path}
                >
                  {isDir ? (
                    <>
                      <ChevronRight className={cn("size-3 shrink-0 text-subtle-foreground transition-transform", open && "rotate-90")} aria-hidden />
                      {open ? <FolderOpen className="size-3.5 shrink-0 text-primary/80" aria-hidden /> : <Folder className="size-3.5 shrink-0 text-primary/70" aria-hidden />}
                    </>
                  ) : (
                    <>
                      <span className="w-3 shrink-0" />
                      <Kind.icon className={cn("size-3.5 shrink-0", Kind.color)} aria-hidden />
                    </>
                  )}
                  <span
                    className={cn(
                      "min-w-0 flex-1 truncate",
                      git?.className,
                      ai && !git && "text-ai",
                      n.gitStatus === "deleted" && "line-through",
                      isDir && marks.changed.has(n.path) && !open && "text-git-modified",
                    )}
                  >
                    {n.name}
                  </span>
                  {ai ? <Sparkles className="size-3 shrink-0 text-ai" aria-label="Changed by AI" /> : null}
                  {isDirty ? <span className="size-1.5 shrink-0 rounded-full bg-foreground" aria-label="Unsaved changes" /> : null}
                  {git ? (
                    <span className={cn("w-3 shrink-0 text-center font-mono text-[12px]", git.className)} aria-label={git.label}>
                      {git.letter}
                    </span>
                  ) : null}
                </button>
              </ContextMenuTrigger>
              <ContextMenuContent>
                {isDir && !readOnly ? (
                  <>
                    <ContextMenuItem onSelect={() => startCreate("file", n.path)}><FilePlus2 /> New file</ContextMenuItem>
                    <ContextMenuItem onSelect={() => startCreate("dir", n.path)}><FolderPlus /> New folder</ContextMenuItem>
                    <ContextMenuSeparator />
                  </>
                ) : null}
                {!readOnly ? <ContextMenuItem onSelect={() => setDraft({ kind: "rename", path: n.path })}><Pencil /> Rename</ContextMenuItem> : null}
                <ContextMenuItem onSelect={() => navigator.clipboard.writeText(n.path)}><Copy /> Copy path</ContextMenuItem>
                {!readOnly ? (
                  <>
                    <ContextMenuSeparator />
                    <ContextMenuItem variant="destructive" onSelect={() => setToDelete(n)}><Trash2 /> Delete</ContextMenuItem>
                  </>
                ) : null}
              </ContextMenuContent>
            </ContextMenu>
            {isDir && open ? (
              <ul
                role="group"
                // A faint guide line under the folder's chevron shows the nesting depth.
                style={{
                  backgroundImage: "linear-gradient(var(--border), var(--border))",
                  backgroundSize: "1px 100%",
                  backgroundRepeat: "no-repeat",
                  backgroundPosition: `${20 + depth * 12}px 0`,
                }}
              >
                {renderNodes(n.children ?? [], depth + 1, n.path)}
              </ul>
            ) : null}
          </li>
        );
      })}
    </>
  );

  const grouped = useMemo(() => {
    const m = new Map<string, FileSearchResult[]>();
    (content.data ?? []).forEach((r) => m.set(r.path, [...(m.get(r.path) ?? []), r]));
    return [...m];
  }, [content.data]);

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex h-10 shrink-0 items-center justify-between gap-1 border-b border-border pl-3.5 pr-2">
        <h2 className="flex items-center gap-2 text-[13px] font-semibold text-foreground">
          Explorer
          {tree.data ? <span className="rounded-full bg-surface-3 px-1.5 text-[11px] font-medium tabular-nums text-muted-foreground">{countFiles(tree.data)}</span> : null}
        </h2>
        <div className="flex items-center">
          {!readOnly ? (
            <>
              <Tooltip content="New file"><Button variant="subtle" size="icon-xs" aria-label="New file" onClick={() => startCreate("file", "")}><FilePlus2 /></Button></Tooltip>
              <Tooltip content="New folder"><Button variant="subtle" size="icon-xs" aria-label="New folder" onClick={() => startCreate("dir", "")}><FolderPlus /></Button></Tooltip>
            </>
          ) : null}
          <Tooltip content="Collapse all"><Button variant="subtle" size="icon-xs" aria-label="Collapse all folders" onClick={() => setExpanded(new Set())}><ChevronsDownUp /></Button></Tooltip>
          <Tooltip content="Refresh"><Button variant="subtle" size="icon-xs" aria-label="Refresh file tree" onClick={() => tree.refetch()}><RefreshCw className={cn(tree.isFetching && "animate-spin")} /></Button></Tooltip>
        </div>
      </div>
      <div className="grid shrink-0 gap-1.5 border-b border-border p-2">
        <div role="tablist" aria-label="Search mode" className="grid grid-cols-2 gap-0.5 rounded-lg bg-surface-2 p-0.5">
          {(
            [
              { value: "names", label: "Names" },
              { value: "content", label: "Contents" },
            ] as const
          ).map((t) => (
            <button
              key={t.value}
              type="button"
              role="tab"
              aria-selected={mode === t.value}
              onClick={() => setMode(t.value)}
              className={cn(
                "h-7 rounded-md text-[12.5px] font-medium outline-none transition-colors focus-visible:ring-2 focus-visible:ring-ring",
                mode === t.value ? "bg-surface-3 text-foreground shadow-[0_1px_2px_rgb(0_0_0/0.3)]" : "text-muted-foreground hover:text-foreground",
              )}
            >
              {t.label}
            </button>
          ))}
        </div>
        <div className="relative">
          <Search className="pointer-events-none absolute left-2 top-1/2 size-3.5 -translate-y-1/2 text-subtle-foreground" aria-hidden />
          <Input
            ref={searchRef}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => e.key === "Escape" && setQuery("")}
            placeholder={mode === "names" ? "Filter files" : "Search in files"}
            aria-label={mode === "names" ? "Filter files by name" : "Search file contents"}
            className="h-8 rounded-lg border-transparent bg-surface-2 pl-7 pr-7 text-[13px] hover:border-transparent"
          />
          {query ? (
            <button className="absolute right-1.5 top-1/2 -translate-y-1/2 text-subtle-foreground hover:text-foreground" aria-label="Clear search" onClick={() => setQuery("")}>
              <X className="size-3.5" />
            </button>
          ) : null}
        </div>
      </div>

      <div
        className={cn("min-h-0 flex-1 overflow-y-auto py-1 transition-colors", dropTarget === "" && "bg-primary-soft/50 ring-1 ring-inset ring-primary/30")}
        // Empty space in the tree is the project root: drop here to move something out of its folder.
        onDragOver={(e) => dragOverFolder(e, "")}
        onDrop={(e) => dropOnFolder(e, "")}
        onDragLeave={(e) => {
          if (!e.currentTarget.contains(e.relatedTarget as Node | null)) {
            setDropTarget(null);
            clearHoverExpand();
          }
        }}
      >
        {mode === "content" && query.trim().length >= 2 ? (
          content.isPending ? <LoadingRows rows={3} /> : content.isError ? <ErrorState error={content.error} compact /> : grouped.length === 0 ? (
            <EmptyState compact title="No matches" />
          ) : (
            <ul className="grid gap-2 px-1">
              <li className="px-2 text-[12px] text-muted-foreground">{content.data?.length} results in {grouped.length} files</li>
              {grouped.map(([path, hits]) => (
                <li key={path}>
                  <p className="flex items-center gap-1.5 truncate px-2 font-mono text-[12px] text-muted-foreground" title={path}>
                    {(() => {
                      const K = fileKind(path);
                      return <K.icon className={cn("size-3.5 shrink-0", K.color)} aria-hidden />;
                    })()}
                    <span className="truncate">{path}</span>
                  </p>
                  <ul>
                    {hits.map((h) => (
                      <li key={`${h.line}:${h.column}`}>
                        <button className="flex w-full gap-2 rounded-md px-2 py-0.5 text-left font-mono text-[12.5px] transition-colors hover:bg-surface-3/70" onClick={() => openFile(projectId, path, { line: h.line, column: h.column })}>
                          <span className="w-7 shrink-0 text-right text-subtle-foreground">{h.line}</span>
                          <span className="truncate">{h.preview}</span>
                        </button>
                      </li>
                    ))}
                  </ul>
                </li>
              ))}
            </ul>
          )
        ) : tree.isPending ? (
          <LoadingRows rows={8} />
        ) : tree.isError ? (
          <ErrorState error={tree.error} onRetry={() => tree.refetch()} compact />
        ) : nodes.length === 0 && !draft ? (
          <EmptyState compact title={needle ? "No files match" : "No files yet"}>
            {needle ? null : "The agent may still be generating this project."}
          </EmptyState>
        ) : (
          <ul role="tree" aria-label="Project files">{renderNodes(nodes, 0, "")}</ul>
        )}
      </div>

      <ConfirmDialog
        open={!!toDelete}
        onOpenChange={(o) => !o && setToDelete(null)}
        title={`Delete ${toDelete?.name}?`}
        description={
          toDelete?.type === "dir"
            ? "This deletes the folder and everything in it. You can restore files from git history."
            : "This deletes the file. You can restore it from git history."
        }
        confirmLabel="Delete"
        destructive
        loading={remove.isPending}
        onConfirm={() => {
          const n = toDelete;
          if (!n) return;
          remove.mutate(n.path, {
            onSuccess: () => {
              removePath(projectId, n.path);
              setToDelete(null);
            },
            onError: (e) => toast.error(errorMessage(e)),
          });
        }}
      />
    </div>
  );
});

function ancestors(path: string): string[] {
  const parts = path.split("/");
  return parts.slice(0, -1).map((_, i) => parts.slice(0, i + 1).join("/"));
}
