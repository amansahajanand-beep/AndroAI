"use client";

import { create } from "zustand";
import { persist } from "zustand/middleware";

export interface ProjectFolder {
  id: string;
  name: string;
  /** ISO time the folder was created. */
  createdAt: string;
}

interface ProjectFoldersState {
  folders: ProjectFolder[];
  /** projectId → folderId. A project is in at most one folder. */
  placement: Record<string, string>;
  create: (name: string) => string;
  rename: (id: string, name: string) => void;
  remove: (id: string) => void;
  move: (projectId: string, folderId: string | null) => void;
}

const newId = () => (typeof crypto !== "undefined" && "randomUUID" in crypto ? crypto.randomUUID() : `f_${Date.now().toString(36)}`);

/**
 * Project folders, saved in this browser only (localStorage). The backend has no folder API yet,
 * so folders don't sync across devices; projects themselves are never changed by this store.
 */
export const useProjectFolders = create<ProjectFoldersState>()(
  persist(
    (set) => ({
      folders: [],
      placement: {},
      create: (name) => {
        const id = newId();
        set((s) => ({ folders: [...s.folders, { id, name: name.trim(), createdAt: new Date().toISOString() }] }));
        return id;
      },
      rename: (id, name) => set((s) => ({ folders: s.folders.map((f) => (f.id === id ? { ...f, name: name.trim() } : f)) })),
      // Deleting a folder keeps its projects; they simply go back to the top level.
      remove: (id) =>
        set((s) => ({
          folders: s.folders.filter((f) => f.id !== id),
          placement: Object.fromEntries(Object.entries(s.placement).filter(([, folderId]) => folderId !== id)),
        })),
      move: (projectId, folderId) =>
        set((s) => {
          const placement = { ...s.placement };
          if (folderId) placement[projectId] = folderId;
          else delete placement[projectId];
          return { placement };
        }),
    }),
    { name: "apppilot.project-folders", version: 1 },
  ),
);
