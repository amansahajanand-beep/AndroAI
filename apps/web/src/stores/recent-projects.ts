"use client";

import { useEffect } from "react";
import { create } from "zustand";
import { persist } from "zustand/middleware";

/** How many recently viewed projects to remember on this device. */
const MAX_RECENT = 8;

export interface RecentProjectView {
  id: string;
  /** ISO time the project was last opened. */
  at: string;
}

interface RecentProjectsState {
  views: RecentProjectView[];
  record: (projectId: string) => void;
}

/**
 * Recently viewed projects, per browser (localStorage). Frontend-only for now:
 * ids that no longer exist are filtered out against the projects list by the reader.
 */
export const useRecentProjects = create<RecentProjectsState>()(
  persist(
    (set) => ({
      views: [],
      record: (id) =>
        set((s) => ({
          views: [{ id, at: new Date().toISOString() }, ...s.views.filter((v) => v.id !== id)].slice(0, MAX_RECENT),
        })),
    }),
    { name: "apppilot.recent-projects", version: 1 },
  ),
);

/** Records a visit to `projectId` when a project page mounts. */
export function useRecordProjectView(projectId: string) {
  const record = useRecentProjects((s) => s.record);
  useEffect(() => {
    record(projectId);
  }, [projectId, record]);
}

/** Render-nothing helper for server-component pages (the IDE route). */
export function RecordProjectView({ projectId }: { projectId: string }) {
  useRecordProjectView(projectId);
  return null;
}
