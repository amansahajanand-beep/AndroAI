"use client";

import { loader, type Monaco } from "@monaco-editor/react";

/**
 * Monaco is served from /monaco/vs (copied from node_modules by
 * scripts/copy-monaco.mjs), never from a third-party CDN.
 */
if (typeof window !== "undefined") {
  loader.config({ paths: { vs: "/monaco/vs" } });
}

const EXT_LANGUAGE: Record<string, string> = {
  kt: "kotlin",
  kts: "kotlin",
  java: "java",
  xml: "xml",
  json: "json",
  yml: "yaml",
  yaml: "yaml",
  md: "markdown",
  gradle: "groovy",
  groovy: "groovy",
  toml: "ini",
  properties: "ini",
  pro: "plaintext",
  txt: "plaintext",
  sh: "shell",
};

export function languageForPath(path: string): string {
  const name = path.slice(path.lastIndexOf("/") + 1).toLowerCase();
  if (name === "gradlew") return "shell";
  const ext = name.includes(".") ? name.slice(name.lastIndexOf(".") + 1) : "";
  return EXT_LANGUAGE[ext] ?? "plaintext";
}

export const LANGUAGE_LABEL: Record<string, string> = {
  kotlin: "Kotlin",
  java: "Java",
  xml: "XML",
  json: "JSON",
  yaml: "YAML",
  markdown: "Markdown",
  groovy: "Gradle (Groovy)",
  ini: "TOML / properties",
  shell: "Shell",
  plaintext: "Plain text",
};

let configured = false;

/** Registers languages Monaco lacks and defines themes from our CSS tokens. */
export function configureMonaco(monaco: Monaco) {
  defineThemes(monaco);
  if (configured) return;
  configured = true;

  if (!monaco.languages.getLanguages().some((l: { id: string }) => l.id === "groovy")) {
    monaco.languages.register({ id: "groovy", extensions: [".gradle", ".groovy"], aliases: ["Groovy", "Gradle"] });
    monaco.languages.setMonarchTokensProvider("groovy", {
      keywords: [
        "abstract", "as", "assert", "boolean", "break", "case", "catch", "class", "def", "default", "do", "double",
        "else", "enum", "extends", "false", "final", "finally", "float", "for", "if", "implements", "import", "in",
        "instanceof", "int", "interface", "long", "new", "null", "package", "private", "protected", "public",
        "return", "static", "super", "switch", "this", "throw", "throws", "true", "try", "void", "while",
        "apply", "plugin", "plugins", "dependencies", "android", "repositories", "implementation", "api",
        "testImplementation", "androidTestImplementation", "kapt", "ksp", "tasks", "register",
      ],
      tokenizer: {
        root: [
          [/[a-zA-Z_$][\w$]*/, { cases: { "@keywords": "keyword", "@default": "identifier" } }],
          [/\/\/.*$/, "comment"],
          [/\/\*/, "comment", "@comment"],
          [/"([^"\\]|\\.)*"/, "string"],
          [/'([^'\\]|\\.)*'/, "string"],
          [/\d+(\.\d+)?/, "number"],
          [/[{}()[\]]/, "@brackets"],
        ],
        comment: [
          [/[^/*]+/, "comment"],
          [/\*\//, "comment", "@pop"],
          [/[/*]/, "comment"],
        ],
      },
    });
    monaco.languages.setLanguageConfiguration("groovy", {
      comments: { lineComment: "//", blockComment: ["/*", "*/"] },
      brackets: [["{", "}"], ["[", "]"], ["(", ")"]],
      autoClosingPairs: [
        { open: "{", close: "}" },
        { open: "[", close: "]" },
        { open: "(", close: ")" },
        { open: '"', close: '"' },
        { open: "'", close: "'" },
      ],
    });
  }
}

/** Editor palettes in AppPilot's own colours; the same values as the design tokens, so it matches the panels. */
const PALETTE = {
  dark: { bg: "#141319", surface: "#19181f", surface2: "#222129", fg: "#f4f3f8", muted: "#6f6d80", border: "#26242f", primary: "#8b7cff" },
  light: { bg: "#ffffff", surface: "#ffffff", surface2: "#f4f3f7", fg: "#16141f", muted: "#8a8799", border: "#e7e5ee", primary: "#5b46e8" },
};

const RULES = {
  dark: [
    { token: "comment", foreground: "6f6d80", fontStyle: "italic" },
    { token: "keyword", foreground: "a99bff" },
    { token: "string", foreground: "8fd19e" },
    { token: "number", foreground: "f0b86e" },
    { token: "type", foreground: "6fd3e6" },
    { token: "tag", foreground: "a99bff" },
    { token: "attribute.name", foreground: "d4b5ff" },
    { token: "attribute.value", foreground: "8fd19e" },
    { token: "annotation", foreground: "f0b86e" },
  ],
  light: [
    { token: "comment", foreground: "7d7a8f", fontStyle: "italic" },
    { token: "keyword", foreground: "5b46e8" },
    { token: "string", foreground: "1f7a3e" },
    { token: "number", foreground: "9a5a00" },
    { token: "type", foreground: "0b7285" },
    { token: "tag", foreground: "5b46e8" },
    { token: "attribute.name", foreground: "7c3aed" },
    { token: "attribute.value", foreground: "1f7a3e" },
    { token: "annotation", foreground: "9a5a00" },
  ],
};

/** Defines the "apppilot" theme for the current app theme (re-run whenever the theme changes). */
function defineThemes(monaco: Monaco) {
  const dark = !document.documentElement.classList.contains("light");
  const { bg, surface, surface2, fg, muted, border, primary } = dark ? PALETTE.dark : PALETTE.light;
  const rules = dark ? RULES.dark : RULES.light;

  monaco.editor.defineTheme("apppilot", {
    base: dark ? "vs-dark" : "vs",
    inherit: true,
    rules,
    colors: {
      "editor.background": bg,
      "editor.foreground": fg,
      "editorLineNumber.foreground": muted,
      "editorLineNumber.activeForeground": fg,
      "editor.lineHighlightBackground": surface2 + "80",
      "editor.lineHighlightBorder": "#00000000",
      "editorCursor.foreground": primary,
      "editorWhitespace.foreground": border,
      "editorBracketMatch.background": primary + "26",
      "editorBracketMatch.border": primary + "66",
      "editorOverviewRuler.border": "#00000000",
      "editor.selectionBackground": primary + "40",
      "editorIndentGuide.background1": border,
      "editorWidget.background": surface,
      "editorWidget.border": border,
      "editorGutter.background": bg,
      "diffEditor.insertedTextBackground": "#3dbe8b26",
      "diffEditor.removedTextBackground": "#f06a6a26",
      "scrollbarSlider.background": border + "aa",
    },
  });
  monaco.editor.setTheme("apppilot");
}
