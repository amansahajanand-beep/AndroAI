"use client";

import { create } from "zustand";
import { persist, createJSONStorage } from "zustand/middleware";
import { useShallow } from "zustand/react/shallow";

export type WorkspaceView = "code" | "preview";
export type BottomTab = "terminal" | "build" | "problems" | "tests" | "git" | "preview";

/** Tabs are file paths, or `review:<changeSetId>` for an agent diff review. */
export const REVIEW_PREFIX = "review:";
export const isReviewTab = (tab: string) => tab.startsWith(REVIEW_PREFIX);

export interface Buffer {
  content: string;
  /** Server version the edits are based on. */
  baseVersion: string;
  dirty: boolean;
}

interface ProjectTabs {
  openTabs: string[];
  active: string | null;
}

interface IdeState {
  /** Persisted: open tabs + active file per project. */
  tabs: Record<string, ProjectTabs>;
  /** Persisted: panel visibility. Sizes are persisted by react-resizable-panels. */
  layout: { explorer: boolean; assistant: boolean; bottom: boolean; bottomTab: BottomTab };
  /** Memory only (never persisted): which main view is showing. Always starts on code. */
  view: WorkspaceView;
  setView: (view: WorkspaceView) => void;
  /** Memory only: unsaved editor buffers keyed by `${projectId}::${path}`. */
  buffers: Record<string, Buffer>;
  /** Memory only: one-shot request to reveal a position in the editor. */
  reveal: { path: string; line: number; column: number; nonce: number } | null;
  /** Memory only: cursor + selection in the active editor (status bar, assistant context). */
  cursor: { path: string; line: number; column: number; selection: { startLine: number; endLine: number; text: string } | null } | null;
  setCursor: (cursor: IdeState["cursor"]) => void;

  openFile: (projectId: string, path: string, opts?: { line?: number; column?: number }) => void;
  closeTab: (projectId: string, tab: string) => void;
  closeOthers: (projectId: string, tab: string) => void;
  setActive: (projectId: string, tab: string) => void;
  openReview: (projectId: string, changeSetId: string) => void;
  renamePath: (projectId: string, from: string, to: string) => void;
  removePath: (projectId: string, path: string) => void;

  setBuffer: (projectId: string, path: string, buffer: Buffer) => void;
  updateBuffer: (projectId: string, path: string, content: string) => void;
  markSaved: (projectId: string, path: string, content: string, version: string) => void;
  dropBuffer: (projectId: string, path: string) => void;

  togglePanel: (panel: "explorer" | "assistant" | "bottom", open?: boolean) => void;
  setBottomTab: (tab: BottomTab) => void;
}

export const bufferKey = (projectId: string, path: string) => `${projectId}::${path}`;

const emptyTabs: ProjectTabs = { openTabs: [], active: null };

export const useIdeStore = create<IdeState>()(
  persist(
    (set, get) => {
      const patchTabs = (projectId: string, fn: (t: ProjectTabs) => ProjectTabs) =>
        set((s) => ({ tabs: { ...s.tabs, [projectId]: fn(s.tabs[projectId] ?? emptyTabs) } }));

      return {
        tabs: {},
        layout: { explorer: true, assistant: true, bottom: true, bottomTab: "problems" },
        view: "code",
        setView: (view) => set({ view }),
        buffers: {},
        reveal: null,
        cursor: null,
        setCursor: (cursor) => set({ cursor }),

        openFile: (projectId, path, opts) => {
          set({ view: "code" });
          patchTabs(projectId, (t) => ({
            openTabs: t.openTabs.includes(path) ? t.openTabs : [...t.openTabs, path],
            active: path,
          }));
          if (opts?.line) set({ reveal: { path, line: opts.line, column: opts.column ?? 1, nonce: Date.now() } });
        },
        closeTab: (projectId, tab) =>
          patchTabs(projectId, (t) => {
            const idx = t.openTabs.indexOf(tab);
            const openTabs = t.openTabs.filter((x) => x !== tab);
            const active =
              t.active === tab ? (openTabs[Math.min(idx, openTabs.length - 1)] ?? null) : t.active;
            return { openTabs, active };
          }),
        closeOthers: (projectId, tab) => patchTabs(projectId, () => ({ openTabs: [tab], active: tab })),
        setActive: (projectId, tab) => patchTabs(projectId, (t) => ({ ...t, active: tab })),
        openReview: (projectId, changeSetId) => get().openFile(projectId, `${REVIEW_PREFIX}${changeSetId}`),
        renamePath: (projectId, from, to) => {
          const re = (p: string) => (p === from ? to : p.startsWith(`${from}/`) ? to + p.slice(from.length) : p);
          patchTabs(projectId, (t) => ({ openTabs: t.openTabs.map(re), active: t.active ? re(t.active) : null }));
          set((s) => {
            const buffers: Record<string, Buffer> = {};
            for (const [k, v] of Object.entries(s.buffers)) {
              const [pid, p] = k.split("::") as [string, string];
              buffers[pid === projectId ? bufferKey(pid, re(p)) : k] = v;
            }
            return { buffers };
          });
        },
        removePath: (projectId, path) => {
          const hit = (p: string) => p === path || p.startsWith(`${path}/`);
          patchTabs(projectId, (t) => {
            const openTabs = t.openTabs.filter((p) => !hit(p));
            return { openTabs, active: t.active && hit(t.active) ? (openTabs[0] ?? null) : t.active };
          });
          set((s) => ({
            buffers: Object.fromEntries(
              Object.entries(s.buffers).filter(([k]) => !(k.startsWith(`${projectId}::`) && hit(k.slice(projectId.length + 2)))),
            ),
          }));
        },

        setBuffer: (projectId, path, buffer) =>
          set((s) => ({ buffers: { ...s.buffers, [bufferKey(projectId, path)]: buffer } })),
        updateBuffer: (projectId, path, content) =>
          set((s) => {
            const k = bufferKey(projectId, path);
            const b = s.buffers[k];
            if (!b) return s;
            return { buffers: { ...s.buffers, [k]: { ...b, content, dirty: true } } };
          }),
        markSaved: (projectId, path, content, version) =>
          set((s) => ({
            buffers: { ...s.buffers, [bufferKey(projectId, path)]: { content, baseVersion: version, dirty: false } },
          })),
        dropBuffer: (projectId, path) =>
          set((s) => {
            const buffers = { ...s.buffers };
            delete buffers[bufferKey(projectId, path)];
            return { buffers };
          }),

        togglePanel: (panel, open) =>
          set((s) => ({ layout: { ...s.layout, [panel]: open ?? !s.layout[panel] } })),
        setBottomTab: (bottomTab) => set((s) => ({ layout: { ...s.layout, bottom: true, bottomTab } })),
      };
    },
    {
      name: "apppilot.ide",
      version: 1,
      storage: createJSONStorage(() => localStorage),
      partialize: (s) => ({
        tabs: Object.fromEntries(
          Object.entries(s.tabs).map(([k, v]) => [
            k,
            { openTabs: v.openTabs.filter((t) => !isReviewTab(t)), active: v.active && isReviewTab(v.active) ? null : v.active },
          ]),
        ),
        layout: s.layout,
      }),
    },
  ),
);

export function useDirtyPaths(projectId: string): string[] {
  return useIdeStore(
    useShallow((s) =>
      Object.entries(s.buffers)
        .filter(([k, b]) => b.dirty && k.startsWith(`${projectId}::`))
        .map(([k]) => k.slice(projectId.length + 2)),
    ),
  );
}
