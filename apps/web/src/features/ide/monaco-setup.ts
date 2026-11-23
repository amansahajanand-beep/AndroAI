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

function cssVar(name: string, fallback: string) {
  if (typeof window === "undefined") return fallback;
  const root = document.documentElement;
  const v = getComputedStyle(root).getPropertyValue(name).trim();
  return /^#[0-9a-f]{6}$/i.test(v) ? v : fallback;
}

function defineThemes(monaco: Monaco) {
  const dark = document.documentElement.classList.contains("light") ? false : true;
  const bg = cssVar("--background", dark ? "#11151c" : "#ffffff");
  const surface = cssVar("--surface", dark ? "#171c25" : "#ffffff");
  const surface2 = cssVar("--surface-2", dark ? "#1d2330" : "#eef1f5");
  const fg = cssVar("--foreground", dark ? "#e4e8f0" : "#151a23");
  const muted = cssVar("--subtle-foreground", dark ? "#66708a" : "#7d8697");
  const border = cssVar("--border", dark ? "#2a3242" : "#d9dee6");
  const primary = cssVar("--primary", dark ? "#6b8cff" : "#3d5fe0");

  const rules = dark
    ? [
        { token: "comment", foreground: "6b7591", fontStyle: "italic" },
        { token: "keyword", foreground: "8fa8ff" },
        { token: "string", foreground: "9fd39a" },
        { token: "number", foreground: "e9b86b" },
        { token: "type", foreground: "6fd0e0" },
        { token: "tag", foreground: "8fa8ff" },
        { token: "attribute.name", foreground: "c6b2f2" },
        { token: "attribute.value", foreground: "9fd39a" },
        { token: "annotation", foreground: "e9b86b" },
      ]
    : [
        { token: "comment", foreground: "7d8697", fontStyle: "italic" },
        { token: "keyword", foreground: "3d5fe0" },
        { token: "string", foreground: "1f7a3e" },
        { token: "number", foreground: "9a5a00" },
        { token: "type", foreground: "0b7285" },
        { token: "tag", foreground: "3d5fe0" },
        { token: "attribute.name", foreground: "6b3fc7" },
        { token: "attribute.value", foreground: "1f7a3e" },
        { token: "annotation", foreground: "9a5a00" },
      ];

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
