"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import { Panel, PanelGroup, PanelResizeHandle } from "react-resizable-panels";
import { useQueryClient } from "@tanstack/react-query";
import type { AgentIntent, FileNode, ProjectStreamEvent } from "@apppilot/contracts";
import {
  AlertCircle,
  AlertTriangle,
  Bot,
  Hammer,
  Keyboard,
  PanelBottom,
  PanelLeft,
  PanelRight,
  Radio,
  Search,
  Sparkles,
} from "lucide-react";
import { toast } from "sonner";
import { LogoMark } from "@/components/brand/logo";
import { MockModeBadge, ThemeToggle, UserMenu } from "@/components/layout/chrome";
import { ErrorState } from "@/components/states/states";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, Tooltip } from "@/components/ui/overlays";
import { Input, Kbd, Skeleton } from "@/components/ui/primitives";
import { errorMessage, isPendingBackend } from "@/lib/api/errors";
import { qk, useAgentTasks, useBuildActions, useDiagnostics, useFileTree, useProject } from "@/lib/api/hooks";
import { useEventStream } from "@/lib/realtime/use-event-stream";
import { cn } from "@/lib/utils";
import { useEditorSettings } from "@/stores/editor-settings";
import { isReviewTab, useDirtyPaths, useIdeStore } from "@/stores/ide-store";
import { ApkAnalysisNotice } from "../projects/project-frame";
import { ProjectTechBadges } from "../projects/project-meta";
import { AssistantPanel } from "./assistant-panel";
import { BottomPanel } from "./bottom-panel";
import { EditorArea } from "./editor-area";
import { FileExplorer, type FileExplorerHandle } from "./file-explorer";
import { PreviewWorkspace } from "./preview-workspace";
import { ViewToggle } from "./view-toggle";
import { LANGUAGE_LABEL, languageForPath } from "./monaco-setup";
import { isMod, MOD, SHORTCUTS } from "./shortcuts";

const PROJECT_EVENTS = ["files.changed", "task.updated", "build.updated", "diagnostics.updated"] as const;

function flatten(nodes: FileNode[], out: FileNode[] = []) {
  for (const n of nodes) {
    if (n.type === "file") out.push(n);
    else flatten(n.children ?? [], out);
  }
  return out;
}

function ResizeHandle({ direction }: { direction: "horizontal" | "vertical" }) {
  return (
    <PanelResizeHandle
      className={cn(
        "relative bg-border transition-colors data-[resize-handle-state=drag]:bg-primary data-[resize-handle-state=hover]:bg-primary/60",
        direction === "horizontal" ? "w-px after:absolute after:inset-y-0 after:-left-1 after:w-2" : "h-px after:absolute after:inset-x-0 after:-top-1 after:h-2",
      )}
    />
  );
}

function QuickOpen({ projectId, open, onOpenChange }: { projectId: string; open: boolean; onOpenChange: (o: boolean) => void }) {
  const tree = useFileTree(projectId);
  const openFile = useIdeStore((s) => s.openFile);
  const [q, setQ] = useState("");
  const [index, setIndex] = useState(0);
  const results = useMemo(() => {
    const files = flatten(tree.data ?? []);
    const n = q.toLowerCase().trim();
    if (!n) return files.slice(0, 50);
    return files
      .map((f) => ({ f, score: f.name.toLowerCase().startsWith(n) ? 0 : f.name.toLowerCase().includes(n) ? 1 : f.path.toLowerCase().includes(n) ? 2 : 9 }))
      .filter((x) => x.score < 9)
      .sort((a, b) => a.score - b.score || a.f.path.length - b.f.path.length)
      .slice(0, 50)
      .map((x) => x.f);
  }, [tree.data, q]);
  const choose = (f: FileNode | undefined) => {
    if (!f) return;
    openFile(projectId, f.path);
    onOpenChange(false);
    setQ("");
  };
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="top-[15%] max-w-xl translate-y-0 gap-0 p-0">
        <DialogTitle className="sr-only">Open file</DialogTitle>
        <DialogDescription className="sr-only">Type to filter files by name and press Enter to open.</DialogDescription>
        <div className="relative border-b border-border">
          <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-subtle-foreground" aria-hidden />
          <Input
            autoFocus
            value={q}
            onChange={(e) => {
              setQ(e.target.value);
              setIndex(0);
            }}
            onKeyDown={(e) => {
              if (e.key === "ArrowDown") { e.preventDefault(); setIndex((i) => Math.min(results.length - 1, i + 1)); }
              if (e.key === "ArrowUp") { e.preventDefault(); setIndex((i) => Math.max(0, i - 1)); }
              if (e.key === "Enter") choose(results[index]);
            }}
            placeholder="Go to file…"
            aria-label="File name"
            role="combobox"
            aria-expanded
            aria-controls="quick-open-list"
            className="h-11 rounded-none border-0 pl-9 text-sm focus-visible:outline-none"
          />
        </div>
        <ul id="quick-open-list" role="listbox" className="max-h-80 overflow-y-auto p-1">
          {results.length === 0 ? <li className="px-3 py-6 text-center text-[14px] text-muted-foreground">No files match.</li> : null}
          {results.map((f, i) => (
            <li key={f.path} role="option" aria-selected={i === index}>
              <button
                onMouseEnter={() => setIndex(i)}
                onClick={() => choose(f)}
                className={cn("flex w-full items-baseline gap-2 rounded-sm px-2 py-1.5 text-left", i === index && "bg-surface-3")}
              >
                <span className={cn("text-[14px]", f.aiModified && "text-ai")}>{f.name}</span>
                <span className="truncate font-mono text-[12px] text-subtle-foreground">{f.path}</span>
              </button>
            </li>
          ))}
        </ul>
      </DialogContent>
    </Dialog>
  );
}

function ShortcutsDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Keyboard shortcuts</DialogTitle>
          <DialogDescription>Editor shortcuts (find, replace, multi-cursor) follow VS Code.</DialogDescription>
        </DialogHeader>
        <ul className="grid gap-1.5 text-[14px]">
          {SHORTCUTS.map((s) => (
            <li key={s.label} className="flex items-center justify-between">
              {s.label}
              <span className="flex gap-1">{s.keys.map((k) => <Kbd key={k}>{k}</Kbd>)}</span>
            </li>
          ))}
        </ul>
      </DialogContent>
    </Dialog>
  );
}

function StatusBar({ projectId, onShortcuts, streamOpen }: { projectId: string; onShortcuts: () => void; streamOpen: boolean }) {
  const diags = useDiagnostics(projectId);
  const tasks = useAgentTasks({ projectId, status: "active" });
  const cursor = useIdeStore((s) => s.cursor);
  const active = useIdeStore((s) => s.tabs[projectId]?.active ?? null);
  const setBottomTab = useIdeStore((s) => s.setBottomTab);
  const tabSize = useEditorSettings((s) => s.tabSize);
  const dirty = useDirtyPaths(projectId);
  const errors = diags.data?.filter((d) => d.severity === "error").length ?? 0;
  const warnings = diags.data?.filter((d) => d.severity === "warning").length ?? 0;
  const running = tasks.data?.length ?? 0;
  const file = active && !isReviewTab(active) ? active : null;

  return (
    <footer className="flex h-6 shrink-0 items-center gap-3 border-t border-border bg-surface px-2 text-[12px] text-muted-foreground">
      <button className="flex items-center gap-2 hover:text-foreground" onClick={() => setBottomTab("problems")} aria-label={`${errors} errors, ${warnings} warnings. Show problems`}>
        <span className="flex items-center gap-1"><AlertCircle className={cn("size-3", errors && "text-destructive")} aria-hidden />{errors}</span>
        <span className="flex items-center gap-1"><AlertTriangle className={cn("size-3", warnings && "text-warning")} aria-hidden />{warnings}</span>
      </button>
      <Link href={`/projects/${projectId}/agent`} className={cn("flex items-center gap-1 hover:text-foreground", running && "text-ai")}>
        {running ? <span className="size-1.5 animate-pulse rounded-full bg-ai" aria-hidden /> : <Bot className="size-3" aria-hidden />}
        {running ? `${running} agent task${running === 1 ? "" : "s"} running` : "No agent tasks running"}
      </Link>
      {dirty.length ? <span>{dirty.length} unsaved</span> : null}
      <span className="ml-auto flex items-center gap-3">
        <Tooltip content={streamOpen ? "Receiving live updates" : "Live updates disconnected; data refreshes on actions"}>
          <span className="flex items-center gap-1"><Radio className={cn("size-3", streamOpen ? "text-success" : "text-warning")} aria-hidden />{streamOpen ? "Live" : "Offline"}</span>
        </Tooltip>
        <MockModeBadge className="h-4 py-0" />
        {file && cursor?.path === file ? <span>Ln {cursor.line}, Col {cursor.column}{cursor.selection ? ` (${cursor.selection.endLine - cursor.selection.startLine + 1} lines selected)` : ""}</span> : null}
        {file ? <span>Spaces: {tabSize}</span> : null}
        {file ? <span>{LANGUAGE_LABEL[languageForPath(file)] ?? "Plain text"}</span> : null}
        <button className="flex items-center gap-1 hover:text-foreground" onClick={onShortcuts} aria-label="Keyboard shortcuts">
          <Keyboard className="size-3" aria-hidden />
        </button>
      </span>
    </footer>
  );
}

export function IdeScreen({ projectId }: { projectId: string }) {
  const project = useProject(projectId);
  const tree = useFileTree(projectId);
  const layout = useIdeStore((s) => s.layout);
  const toggle = useIdeStore((s) => s.togglePanel);
  const view = useIdeStore((s) => s.view);
  const setView = useIdeStore((s) => s.setView);
  const setBottomTab = useIdeStore((s) => s.setBottomTab);
  const openFile = useIdeStore((s) => s.openFile);
  const closeTab = useIdeStore((s) => s.closeTab);
  const dirty = useDirtyPaths(projectId);
  const { start } = useBuildActions(projectId);
  const qc = useQueryClient();
  const params = useSearchParams();
  const router = useRouter();
  const explorerRef = useRef<FileExplorerHandle>(null);
  const [quickOpen, setQuickOpen] = useState(false);
  const [shortcuts, setShortcuts] = useState(false);
  const readOnly = project.data?.isApkAnalysis;
  const readOnlyRef = useRef(readOnly);
  useEffect(() => {
    readOnlyRef.current = readOnly;
  }, [readOnly]);

  const aiModifiedPaths = useMemo(() => new Set(flatten(tree.data ?? []).filter((f) => f.aiModified).map((f) => f.path)), [tree.data]);

  // Every project opens on Code, never on Preview.
  useEffect(() => {
    setView("code");
  }, [projectId, setView]);

  // Deep links: ?open=path&line=n (from build errors), ?assistant=intent.
  const handledLink = useRef(false);
  useEffect(() => {
    if (handledLink.current) return;
    const path = params.get("open");
    const assistant = params.get("assistant");
    if (path) openFile(projectId, path, { line: Number(params.get("line")) || 1 });
    if (assistant) toggle("assistant", true);
    if (path || assistant) {
      handledLink.current = true;
      router.replace(`/projects/${projectId}/ide${assistant ? `?assistant=${assistant}` : ""}`, { scroll: false });
    }
  }, [params, projectId, openFile, toggle, router]);

  // Warn before closing the tab with unsaved buffers.
  useEffect(() => {
    if (!dirty.length) return;
    const handler = (e: BeforeUnloadEvent) => {
      e.preventDefault();
    };
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [dirty.length]);

  // Global shortcuts.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const mod = isMod(e);
      const k = e.key.toLowerCase();
      if (mod && e.altKey && k === "b") { e.preventDefault(); toggle("assistant"); return; }
      if (mod && e.altKey && k === "p") {
        e.preventDefault();
        const s = useIdeStore.getState();
        if (s.view === "preview") s.setView("code");
        else if (!readOnlyRef.current) s.setView("preview");
        return;
      }
      if (mod && !e.shiftKey && k === "b") { e.preventDefault(); toggle("explorer"); return; }
      if (mod && k === "j") { e.preventDefault(); toggle("bottom"); return; }
      if (mod && !e.shiftKey && k === "p") { e.preventDefault(); setQuickOpen(true); return; }
      if (mod && e.shiftKey && k === "f") { e.preventDefault(); toggle("explorer", true); setTimeout(() => explorerRef.current?.focusSearch("content")); return; }
      if (mod && k === "/") { e.preventDefault(); setShortcuts(true); return; }
      if (e.altKey && !mod && k === "w") {
        const active = useIdeStore.getState().tabs[projectId]?.active;
        if (active) { e.preventDefault(); closeTab(projectId, active); }
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [toggle, projectId, closeTab]);

  // Live project events from the backend.
  const stream = useEventStream({
    endpoint: "projects.events",
    params: { projectId },
    events: PROJECT_EVENTS,
    onEvent: (_type, raw) => {
      const ev = raw as ProjectStreamEvent;
      if (ev.type === "files.changed") {
        qc.invalidateQueries({ queryKey: qk.tree(projectId) });
        const buffers = useIdeStore.getState().buffers;
        ev.paths.forEach((p) => {
          qc.invalidateQueries({ queryKey: qk.file(projectId, p) });
          if (buffers[`${projectId}::${p}`]?.dirty) toast.warning(`${p.split("/").pop()} changed on the server while you have unsaved edits.`);
        });
      } else if (ev.type === "task.updated") {
        qc.invalidateQueries({ queryKey: ["agent", "tasks"] });
      } else if (ev.type === "build.updated") {
        qc.invalidateQueries({ queryKey: ["builds"] });
        // A finished build may make a blocked preview possible. Never replace a session that is already running.
        if (qc.getQueryState(qk.previewSession(projectId))?.status === "error") {
          qc.invalidateQueries({ queryKey: qk.previewSession(projectId) });
        }
        qc.invalidateQueries({ queryKey: qk.diagnostics(projectId) });
      } else if (ev.type === "diagnostics.updated") {
        qc.invalidateQueries({ queryKey: qk.diagnostics(projectId) });
      }
    },
  });

  const assistantIntent = params.get("assistant") as AgentIntent | null;

  if (project.isError) {
    return (
      <div className="grid h-dvh place-items-center">
        <ErrorState error={project.error} onRetry={() => project.refetch()} />
      </div>
    );
  }

  return (
    <div className="flex h-dvh flex-col overflow-hidden">
      <header className="flex h-11 shrink-0 items-center gap-2 border-b border-border bg-surface px-2">
        <Tooltip content="All projects">
          <Link href="/projects" className="grid size-8 place-items-center rounded-sm hover:bg-surface-2" aria-label="All projects">
            <LogoMark className="size-5" />
          </Link>
        </Tooltip>
        <div className="flex min-w-0 items-center gap-2">
          {project.data ? (
            <>
              <h1 className="truncate text-[14px] font-semibold">{project.data.name}</h1>
              <span className="hidden lg:block"><ProjectTechBadges project={project.data} /></span>
            </>
          ) : (
            <Skeleton className="h-4 w-32" />
          )}
        </div>
        <nav aria-label="Project" className="ml-2 hidden items-center gap-0.5 md:flex">
          {[
            ["agent", "AI agent"],
            ["builds", "Builds"],
            ["tests", "Tests"],
            ["settings", "Settings"],
          ].map(([seg, label]) => (
            <Link key={seg} href={`/projects/${projectId}/${seg}`} className="rounded-sm px-2 py-1 text-[13px] text-muted-foreground hover:bg-surface-2 hover:text-foreground">
              {label}
            </Link>
          ))}
        </nav>
        <ViewToggle
          value={view}
          onChange={setView}
          previewDisabledReason={readOnly ? "Preview isn't available for APK analyses (decompiled, read-only)" : undefined}
        />
        <div className="ml-auto flex items-center gap-1">
          {!readOnly ? (
            <Button
              size="sm"
              variant="outline"
              loading={start.isPending}
              onClick={() =>
                start.mutate(
                  { projectId, outputType: "apk", variant: "debug" },
                  {
                    onSuccess: (b) => {
                      toast.success(`Build #${b.number} started`);
                      setBottomTab("build");
                    },
                    onError: (e) => toast.error(isPendingBackend(e) ? "Builds aren't available yet — the build endpoint is pending." : errorMessage(e)),
                  },
                )
              }
            >
              <Hammer /> Build
            </Button>
          ) : null}
          <span className="mx-1 h-5 w-px bg-border" aria-hidden />
          <Tooltip content="Explorer" shortcut={`${MOD}+B`}>
            <Button variant={layout.explorer ? "secondary" : "subtle"} size="icon-sm" aria-pressed={layout.explorer} aria-label="Toggle explorer" onClick={() => toggle("explorer")}><PanelLeft /></Button>
          </Tooltip>
          <Tooltip content="Bottom panel" shortcut={`${MOD}+J`}>
            <Button variant={layout.bottom ? "secondary" : "subtle"} size="icon-sm" aria-pressed={layout.bottom} aria-label="Toggle bottom panel" onClick={() => toggle("bottom")}><PanelBottom /></Button>
          </Tooltip>
          <Tooltip content="AI assistant" shortcut={`${MOD}+Alt+B`}>
            <Button variant={layout.assistant ? "secondary" : "subtle"} size="icon-sm" aria-pressed={layout.assistant} aria-label="Toggle AI assistant" onClick={() => toggle("assistant")}>
              {layout.assistant ? <PanelRight /> : <Sparkles className="text-ai" />}
            </Button>
          </Tooltip>
          <span className="mx-1 h-5 w-px bg-border" aria-hidden />
          <ThemeToggle />
          <UserMenu compact />
        </div>
      </header>

      {readOnly ? <ApkAnalysisNotice className="m-2 mb-0 rounded-md" /> : null}

      <PanelGroup direction="horizontal" autoSaveId="apppilot.ide.h" className="min-h-0 flex-1">
        {layout.explorer ? (
          <>
            <Panel id="explorer" order={1} defaultSize={18} minSize={12} maxSize={35}>
              <FileExplorer ref={explorerRef} projectId={projectId} readOnly={readOnly} />
            </Panel>
            <ResizeHandle direction="horizontal" />
          </>
        ) : null}
        <Panel id="center" order={2} minSize={30}>
          <div className="relative size-full">
          {/* The editor stays mounted (just hidden) while previewing, so tabs, unsaved buffers and cursor survive. */}
          <div
            id="view-panel-code"
            role="tabpanel"
            aria-labelledby="view-tab-code"
            aria-hidden={view === "preview"}
            inert={view === "preview"}
            className={cn("size-full transition-opacity duration-200", view === "preview" && "invisible opacity-0")}
          >
          <PanelGroup direction="vertical" autoSaveId="apppilot.ide.v">
            <Panel id="editor" order={1} minSize={20}>
              <EditorArea projectId={projectId} aiModifiedPaths={aiModifiedPaths} readOnly={readOnly} />
            </Panel>
            {layout.bottom ? (
              <>
                <ResizeHandle direction="vertical" />
                <Panel id="bottom" order={2} defaultSize={30} minSize={10} maxSize={70}>
                  <BottomPanel projectId={projectId} readOnly={readOnly} />
                </Panel>
              </>
            ) : null}
          </PanelGroup>
          </div>
          {view === "preview" ? <PreviewWorkspace projectId={projectId} /> : null}
          </div>
        </Panel>
        {layout.assistant ? (
          <>
            <ResizeHandle direction="horizontal" />
            <Panel id="assistant" order={3} defaultSize={26} minSize={18} maxSize={45}>
              <AssistantPanel projectId={projectId} initialIntent={assistantIntent ?? undefined} isApk={readOnly} onClose={() => toggle("assistant", false)} />
            </Panel>
          </>
        ) : null}
      </PanelGroup>

      <StatusBar projectId={projectId} onShortcuts={() => setShortcuts(true)} streamOpen={stream === "open"} />
      <QuickOpen projectId={projectId} open={quickOpen} onOpenChange={setQuickOpen} />
      <ShortcutsDialog open={shortcuts} onOpenChange={setShortcuts} />
    </div>
  );
}
