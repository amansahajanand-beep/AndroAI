"use client";

import { create } from "zustand";
import { persist } from "zustand/middleware";

/** Persistent per-browser editor settings (localStorage). */
export interface EditorSettings {
  fontSize: number;
  tabSize: 2 | 4;
  wordWrap: boolean;
  minimap: boolean;
  lineNumbers: boolean;
  set: (patch: Partial<Omit<EditorSettings, "set" | "reset">>) => void;
  reset: () => void;
}

const DEFAULTS = {
  fontSize: 13,
  tabSize: 4 as const,
  wordWrap: false,
  minimap: false,
  lineNumbers: true,
};

export const useEditorSettings = create<EditorSettings>()(
  persist(
    (set) => ({
      ...DEFAULTS,
      set: (patch) => set(patch),
      reset: () => set(DEFAULTS),
    }),
    { name: "apppilot.editor-settings", version: 1 },
  ),
);
