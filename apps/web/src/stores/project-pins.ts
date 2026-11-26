"use client";

import { create } from "zustand";
import { persist } from "zustand/middleware";

interface ProjectPinsState {
  /** Pinned project ids, most recently pinned first. */
  pinned: string[];
  toggle: (projectId: string) => void;
}

/**
 * Pinned projects, saved in this browser (localStorage) so they survive a refresh.
 * The backend has no pin field; projects themselves are never changed by this store.
 */
export const useProjectPins = create<ProjectPinsState>()(
  persist(
    (set) => ({
      pinned: [],
      toggle: (id) => set((s) => ({ pinned: s.pinned.includes(id) ? s.pinned.filter((p) => p !== id) : [id, ...s.pinned] })),
    }),
    { name: "apppilot.project-pins", version: 1 },
  ),
);

/** Stable "pinned first" ordering: pinned projects (most recently pinned first), then the rest in their existing order. */
export function pinnedFirst<T extends { id: string }>(items: T[], pinned: string[]): T[] {
  const rank = new Map(pinned.map((id, i) => [id, i]));
  const last = Number.MAX_SAFE_INTEGER;
  return [...items].sort((a, b) => (rank.get(a.id) ?? last) - (rank.get(b.id) ?? last));
}
