"use client";

import { useState } from "react";
import { ChevronRight, Code2, Columns2, FileCode2, Sparkles, X } from "lucide-react";
import { EmptyState } from "@/components/states/states";
import { Button } from "@/components/ui/button";
import { ContextMenu, ContextMenuContent, ContextMenuItem, ContextMenuTrigger, Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, Tooltip } from "@/components/ui/overlays";
import { Badge, Kbd } from "@/components/ui/primitives";
import { useFileMutations } from "@/lib/api/hooks";
import { basename, cn } from "@/lib/utils";
import { bufferKey, isReviewTab, REVIEW_PREFIX, useIdeStore } from "@/stores/ide-store";
import { ChangeReview } from "./change-review";
import { CodeEditor, UnsavedDiff } from "./code-editor";
import { MOD } from "./shortcuts";

function Breadcrumbs({ path, aiModified, onToggleDiff, showDiff, dirty }: { path: string; aiModified: boolean; onToggleDiff: () => void; showDiff: boolean; dirty: boolean }) {
  const parts = path.split("/");
  return (
    <div className="flex h-8 items-center gap-1 border-b border-border px-3.5 text-[12.5px] text-muted-foreground">
      <nav aria-label="File path" className="flex min-w-0 items-center gap-1 overflow-hidden">
        {parts.map((p, i) => (
          <span key={i} className="flex shrink-0 items-center gap-1 last:shrink">
            {i > 0 ? <ChevronRight className="size-3 text-subtle-foreground" aria-hidden /> : null}
            <span className={cn(i === parts.length - 1 && "truncate text-foreground")}>{p}</span>
          </span>
        ))}
      </nav>
      {aiModified ? (
        <Badge tone="ai" className="ml-2 shrink-0" title="The last change to this file came from an AI agent. Marked lines show what it wrote.">
          <Sparkles aria-hidden /> AI-edited
        </Badge>
      ) : null}
      {dirty ? (
        <Tooltip content={showDiff ? "Back to editor" : "Compare with saved version"}>
          <Button variant={showDiff ? "secondary" : "subtle"} size="icon-xs" className="ml-auto" aria-pressed={showDiff} aria-label="Compare with saved version" onClick={onToggleDiff}>
            <Columns2 />
          </Button>
        </Tooltip>
      ) : null}
    </div>
  );
}

export function EditorArea({ projectId, aiModifiedPaths, readOnly }: { projectId: string; aiModifiedPaths: Set<string>; readOnly?: boolean }) {
  const tabs = useIdeStore((s) => s.tabs[projectId]);
  const buffers = useIdeStore((s) => s.buffers);
  const setActive = useIdeStore((s) => s.setActive);
  const closeTab = useIdeStore((s) => s.closeTab);
  const closeOthers = useIdeStore((s) => s.closeOthers);
  const dropBuffer = useIdeStore((s) => s.dropBuffer);
  const { save } = useFileMutations(projectId);
  const markSaved = useIdeStore((s) => s.markSaved);
  const [confirmClose, setConfirmClose] = useState<string | null>(null);
  const [diffFor, setDiffFor] = useState<string | null>(null);

  const open = tabs?.openTabs ?? [];
  const active = tabs?.active ?? null;
  const isDirty = (t: string) => !isReviewTab(t) && !!buffers[bufferKey(projectId, t)]?.dirty;

  const requestClose = (t: string) => {
    if (isDirty(t)) setConfirmClose(t);
    else {
      closeTab(projectId, t);
      if (!isReviewTab(t)) dropBuffer(projectId, t);
    }
  };

  if (!active) {
    return (
      <EmptyState icon={<Code2 />} title="No file open" className="h-full">
        <span className="grid gap-1.5">
          <span>Pick a file in the explorer, or press <Kbd>{MOD}</Kbd> <Kbd>P</Kbd> to open one by name.</span>
        </span>
      </EmptyState>
    );
  }

  const activeIsReview = isReviewTab(active);
  const showDiff = diffFor === active && isDirty(active);

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div role="tablist" aria-label="Open files" className="flex h-10 shrink-0 items-center gap-1 overflow-x-auto border-b border-border px-2">
        {open.map((t) => {
          const review = isReviewTab(t);
          const dirty = isDirty(t);
          const selected = t === active;
          return (
            <ContextMenu key={t}>
              <ContextMenuTrigger asChild>
                <div
                  role="tab"
                  aria-selected={selected}
                  tabIndex={selected ? 0 : -1}
                  title={review ? "Review agent changes" : t}
                  onClick={() => setActive(projectId, t)}
                  onKeyDown={(e) => e.key === "Enter" && setActive(projectId, t)}
                  onAuxClick={(e) => e.button === 1 && requestClose(t)}
                  className={cn(
                    "group flex h-7 shrink-0 cursor-pointer items-center gap-1.5 rounded-lg pl-2.5 pr-1 text-[13px] outline-none transition-colors focus-visible:ring-2 focus-visible:ring-ring",
                    selected ? "bg-surface-3 text-foreground" : "text-muted-foreground hover:bg-surface-2 hover:text-foreground",
                  )}
                >
                  {review ? <Sparkles className="size-3.5 text-ai" aria-hidden /> : <FileCode2 className={cn("size-3.5", aiModifiedPaths.has(t) ? "text-ai" : "text-subtle-foreground")} aria-hidden />}
                  <span className="max-w-44 truncate">{review ? "Review changes" : basename(t)}</span>
                  <button
                    className="relative grid size-5 place-items-center rounded-md transition-colors hover:bg-surface-3"
                    aria-label={dirty ? `${basename(t)} has unsaved changes. Close` : `Close ${review ? "review" : basename(t)}`}
                    onClick={(e) => {
                      e.stopPropagation();
                      requestClose(t);
                    }}
                  >
                    {dirty ? (
                      <>
                        <span className="size-2 rounded-full bg-foreground group-hover:hidden" aria-hidden />
                        <X className="hidden size-3.5 group-hover:block" aria-hidden />
                      </>
                    ) : (
                      <X className={cn("size-3.5", !selected && "opacity-0 group-hover:opacity-100")} aria-hidden />
                    )}
                  </button>
                </div>
              </ContextMenuTrigger>
              <ContextMenuContent>
                <ContextMenuItem onSelect={() => requestClose(t)}>Close</ContextMenuItem>
                <ContextMenuItem onSelect={() => closeOthers(projectId, t)}>Close others</ContextMenuItem>
                {!review ? <ContextMenuItem onSelect={() => navigator.clipboard.writeText(t)}>Copy path</ContextMenuItem> : null}
              </ContextMenuContent>
            </ContextMenu>
          );
        })}
      </div>

      {activeIsReview ? (
        <div className="min-h-0 flex-1">
          <ChangeReview key={active} changeSetId={active.slice(REVIEW_PREFIX.length)} projectId={projectId} />
        </div>
      ) : (
        <>
          <Breadcrumbs path={active} aiModified={aiModifiedPaths.has(active)} dirty={isDirty(active)} showDiff={showDiff} onToggleDiff={() => setDiffFor(showDiff ? null : active)} />
          <div className="min-h-0 flex-1">
            {showDiff ? <UnsavedDiff projectId={projectId} path={active} /> : null}
            <div className={cn("h-full", showDiff && "hidden")}>
              <CodeEditor projectId={projectId} path={active} readOnly={readOnly} />
            </div>
          </div>
        </>
      )}

      <Dialog open={!!confirmClose} onOpenChange={(o) => !o && setConfirmClose(null)}>
        <DialogContent role="alertdialog">
          <DialogHeader>
            <DialogTitle>Save changes to {confirmClose ? basename(confirmClose) : "file"}?</DialogTitle>
            <DialogDescription>Your changes will be lost if you don&apos;t save them.</DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setConfirmClose(null)}>Cancel</Button>
            <Button
              variant="outline"
              onClick={() => {
                if (!confirmClose) return;
                closeTab(projectId, confirmClose);
                dropBuffer(projectId, confirmClose);
                setConfirmClose(null);
              }}
            >
              Don&apos;t save
            </Button>
            <Button
              loading={save.isPending}
              onClick={() => {
                const path = confirmClose;
                const b = path ? useIdeStore.getState().buffers[bufferKey(projectId, path)] : undefined;
                if (!path || !b) return;
                save.mutate(
                  { path, content: b.content, baseVersion: b.baseVersion },
                  {
                    onSuccess: (f) => {
                      markSaved(projectId, path, b.content, f.version);
                      closeTab(projectId, path);
                      dropBuffer(projectId, path);
                      setConfirmClose(null);
                    },
                  },
                );
              }}
            >
              Save
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
