"use client";

/** Platform-aware modifier label. Evaluated once on the client. */
export const IS_MAC = typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent);
export const MOD = IS_MAC ? "⌘" : "Ctrl";
export const ALT = IS_MAC ? "⌥" : "Alt";

export const SHORTCUTS = [
  { keys: [MOD, "S"], label: "Save file" },
  { keys: [MOD, "P"], label: "Open file by name" },
  { keys: [MOD, "B"], label: "Toggle explorer" },
  { keys: [MOD, "J"], label: "Toggle bottom panel" },
  { keys: [MOD, ALT, "B"], label: "Toggle AI assistant" },
  { keys: [MOD, ALT, "P"], label: "Switch between Preview and Code" },
  { keys: [MOD, "Shift", "F"], label: "Search in files" },
  { keys: [ALT, "W"], label: "Close tab" },
  { keys: [MOD, "Enter"], label: "Send to assistant" },
  { keys: [MOD, "F"], label: "Find (in editor)" },
  { keys: [MOD, "H"], label: "Replace (in editor)" },
  { keys: [MOD, "Z"], label: "Undo" },
  { keys: [MOD, "Shift", "Z"], label: "Redo" },
  { keys: [MOD, "/"], label: "Show shortcuts" },
] as const;

export const isMod = (e: KeyboardEvent | React.KeyboardEvent) => (IS_MAC ? e.metaKey : e.ctrlKey);
