"use client";

import { forwardRef, useEffect, useImperativeHandle, useMemo, useRef, useState } from "react";
import type { FileNode, FileSearchResult, GitFileStatus } from "@apppilot/contracts";
import {
  ChevronRight,
  ChevronsDownUp,
  Copy,
  FileCode2,
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
} from "lucide-react";
import { toast } from "sonner";
import { ErrorState, LoadingRows, EmptyState } from "@/components/states/states";
import { Button } from "@/components/ui/button";
import { ConfirmDialog, ContextMenu, ContextMenuContent, ContextMenuItem, ContextMenuSeparator, ContextMenuTrigger, Segmented, Tooltip } from "@/components/ui/overlays";
import { Input } from "@/components/ui/primitives";
import { errorMessage } from "@/lib/api/errors";
import { useFileMutations, useFileSearch, useFileTree } from "@/lib/api/hooks";
import { cn, dirname } from "@/lib/utils";
import { useDirtyPaths, useIdeStore } from "@/stores/ide-store";

const GIT_MARK: Record<GitFileStatus, { letter: string; className: string; label: string }> = {
  modified: { letter: "M", className: "text-git-modified", label: "Modified" },
  added: { letter: "A", className: "text-git-added", label: "Added" },
  deleted: { letter: "D", className: "text-git-deleted", label: "Deleted" },
  untracked: { letter: "U", className: "text-git-untracked", label: "Untracked" },
};

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
        return (
          <li key={n.path} role="treeitem" aria-expanded={isDir ? open : undefined} aria-selected={active === n.path}>
            <ContextMenu>
              <ContextMenuTrigger asChild>
                <button
                  className={cn(
                    "group flex h-6 w-full items-center gap-1.5 pr-2 text-left text-[14px] hover:bg-surface-2 focus-visible:outline-offset-[-2px]",
                    active === n.path && "bg-primary-soft text-foreground",
                  )}
                  style={{ paddingLeft: 8 + depth * 12 }}
                  onClick={() => (isDir ? toggle(n.path) : openFile(projectId, n.path))}
                  title={n.path}
                >
                  {isDir ? (
                    <>
                      <ChevronRight className={cn("size-3 shrink-0 text-subtle-foreground transition-transform", open && "rotate-90")} aria-hidden />
                      {open ? <FolderOpen className="size-3.5 shrink-0 text-muted-foreground" aria-hidden /> : <Folder className="size-3.5 shrink-0 text-muted-foreground" aria-hidden />}
                    </>
                  ) : (
                    <>
                      <span className="w-3 shrink-0" />
                      <FileCode2 className={cn("size-3.5 shrink-0", ai ? "text-ai" : "text-subtle-foreground")} aria-hidden />
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
            {isDir && open ? <ul role="group">{renderNodes(n.children ?? [], depth + 1, n.path)}</ul> : null}
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
    <div className="flex h-full min-h-0 flex-col bg-surface">
      <div className="flex h-9 shrink-0 items-center justify-between gap-1 border-b border-border pl-3 pr-1.5">
        <h2 className="text-[13px] font-semibold text-muted-foreground">Explorer</h2>
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
        <div className="relative">
          <Search className="pointer-events-none absolute left-2 top-1/2 size-3.5 -translate-y-1/2 text-subtle-foreground" aria-hidden />
          <Input
            ref={searchRef}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => e.key === "Escape" && setQuery("")}
            placeholder={mode === "names" ? "Filter files" : "Search in files"}
            aria-label={mode === "names" ? "Filter files by name" : "Search file contents"}
            className="h-7 pl-7 pr-7 text-[13px]"
          />
          {query ? (
            <button className="absolute right-1.5 top-1/2 -translate-y-1/2 text-subtle-foreground hover:text-foreground" aria-label="Clear search" onClick={() => setQuery("")}>
              <X className="size-3.5" />
            </button>
          ) : null}
        </div>
        <Segmented aria-label="Search mode" value={mode} onChange={setMode} className="w-full [&>button]:flex-1 [&>button]:justify-center [&>button]:text-[13px]" options={[{ value: "names", label: "Names" }, { value: "content", label: "Contents" }]} />
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto py-1">
        {mode === "content" && query.trim().length >= 2 ? (
          content.isPending ? <LoadingRows rows={3} /> : content.isError ? <ErrorState error={content.error} compact /> : grouped.length === 0 ? (
            <EmptyState compact title="No matches" />
          ) : (
            <ul className="grid gap-2 px-1">
              <li className="px-2 text-[12px] text-muted-foreground">{content.data?.length} results in {grouped.length} files</li>
              {grouped.map(([path, hits]) => (
                <li key={path}>
                  <p className="truncate px-2 font-mono text-[12px] text-muted-foreground" title={path}>{path}</p>
                  <ul>
                    {hits.map((h) => (
                      <li key={`${h.line}:${h.column}`}>
                        <button className="flex w-full gap-2 rounded-sm px-2 py-0.5 text-left font-mono text-[13px] hover:bg-surface-2" onClick={() => openFile(projectId, path, { line: h.line, column: h.column })}>
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
