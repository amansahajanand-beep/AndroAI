"use client";

import { create } from "zustand";
import { persist } from "zustand/middleware";

interface UiState {
  sidebarCollapsed: boolean;
  projectsView: "grid" | "list";
  toggleSidebar: () => void;
  setProjectsView: (v: "grid" | "list") => void;
}

export const useUiStore = create<UiState>()(
  persist(
    (set) => ({
      sidebarCollapsed: false,
      projectsView: "grid",
      toggleSidebar: () => set((s) => ({ sidebarCollapsed: !s.sidebarCollapsed })),
      setProjectsView: (projectsView) => set({ projectsView }),
    }),
    { name: "apppilot.ui", version: 1 },
  ),
);
