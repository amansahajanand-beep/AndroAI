"use client";

import Editor, { DiffEditor, type DiffEditorProps, type Monaco, type OnMount } from "@monaco-editor/react";
import { useTheme } from "next-themes";
import { useCallback, useEffect, useRef, useState } from "react";
import type { editor as MonacoEditorNs } from "monaco-editor";
import { AlertTriangle, Loader2 } from "lucide-react";
import { toast } from "sonner";
import { ErrorState } from "@/components/states/states";
import { Button } from "@/components/ui/button";
import { Alert } from "@/components/ui/primitives";
import { ApiError, errorMessage } from "@/lib/api/errors";
import { useFile, useFileMutations } from "@/lib/api/hooks";
import { useEditorSettings } from "@/stores/editor-settings";
import { bufferKey, useIdeStore } from "@/stores/ide-store";
import { configureMonaco, languageForPath } from "./monaco-setup";

export function EditorLoading() {
  return (
    <div className="grid h-full place-items-center text-muted-foreground" aria-busy="true">
      <Loader2 className="size-5 animate-spin" aria-label="Loading editor" />
    </div>
  );
}

function useEditorOptions(readOnly = false): MonacoEditorNs.IStandaloneEditorConstructionOptions {
  const s = useEditorSettings();
  return {
    fontFamily: '"JetBrains Mono Variable", ui-monospace, monospace',
    fontLigatures: true,
    fontSize: s.fontSize,
    tabSize: s.tabSize,
    wordWrap: s.wordWrap ? "on" : "off",
    minimap: { enabled: s.minimap },
    lineNumbers: s.lineNumbers ? "on" : "off",
    readOnly,
    scrollBeyondLastLine: false,
    smoothScrolling: true,
    renderLineHighlight: "all",
    automaticLayout: true,
    padding: { top: 8 },
    stickyScroll: { enabled: true },
    bracketPairColorization: { enabled: true },
    guides: { bracketPairs: "active" },
  };
}

/** Re-applies our Monaco theme whenever the app theme changes. */
function useMonacoTheme(monacoRef: React.RefObject<Monaco | null>) {
  const { resolvedTheme } = useTheme();
  useEffect(() => {
    const id = requestAnimationFrame(() => monacoRef.current && configureMonaco(monacoRef.current));
    return () => cancelAnimationFrame(id);
  }, [resolvedTheme, monacoRef]);
}

export function CodeEditor({ projectId, path, readOnly }: { projectId: string; path: string; readOnly?: boolean }) {
  const file = useFile(projectId, path);
  const key = bufferKey(projectId, path);
  const buffer = useIdeStore((s) => s.buffers[key]);
  const setBuffer = useIdeStore((s) => s.setBuffer);
  const updateBuffer = useIdeStore((s) => s.updateBuffer);
  const markSaved = useIdeStore((s) => s.markSaved);
  const dropBuffer = useIdeStore((s) => s.dropBuffer);
  const setCursor = useIdeStore((s) => s.setCursor);
  const reveal = useIdeStore((s) => s.reveal);
  const { save } = useFileMutations(projectId);
  const options = useEditorOptions(readOnly || file.data?.binary);
  const editorRef = useRef<MonacoEditorNs.IStandaloneCodeEditor | null>(null);
  const monacoRef = useRef<Monaco | null>(null);
  const decorations = useRef<MonacoEditorNs.IEditorDecorationsCollection | null>(null);
  const [mounted, setMounted] = useState(false);
  // One editor instance serves every tab (Monaco keeps a model + undo stack per path).
  const pathRef = useRef(path);
  useEffect(() => {
    pathRef.current = path;
  }, [path]);
  useMonacoTheme(monacoRef);

  const serverChanged = !!buffer && !!file.data && buffer.dirty && file.data.version !== buffer.baseVersion;

  // Seed the buffer from the server, and follow server updates while clean.
  useEffect(() => {
    if (!file.data) return;
    if (!buffer || (!buffer.dirty && buffer.baseVersion !== file.data.version)) {
      setBuffer(projectId, path, { content: file.data.content, baseVersion: file.data.version, dirty: false });
    }
  }, [file.data, buffer, projectId, path, setBuffer]);

  const doSave = useCallback(
    (force = false) => {
      const b = useIdeStore.getState().buffers[key];
      if (!b || (!b.dirty && !force)) return;
      save.mutate(
        { path, content: b.content, baseVersion: b.baseVersion },
        {
          onSuccess: (f) => markSaved(projectId, path, b.content, f.version),
          onError: (e) => {
            if (e instanceof ApiError && e.code === "file.version_conflict") {
              toast.error(`${path.split("/").pop()} changed on the server since you opened it.`, {
                description: "Overwrite it with your version, or discard your edits and load the latest.",
                duration: 15_000,
                action: {
                  label: "Overwrite",
                  onClick: async () => {
                    const latest = await file.refetch();
                    if (!latest.data) return;
                    save.mutate(
                      { path, content: b.content, baseVersion: latest.data.version },
                      { onSuccess: (f) => markSaved(projectId, path, b.content, f.version), onError: (err) => toast.error(errorMessage(err)) },
                    );
                  },
                },
                cancel: {
                  label: "Load latest",
                  onClick: () => {
                    dropBuffer(projectId, path);
                    file.refetch();
                  },
                },
              });
            } else toast.error(`Couldn't save: ${errorMessage(e)}`);
          },
        },
      );
    },
    [key, path, projectId, save, markSaved, dropBuffer, file],
  );
  const saveRef = useRef(doSave);
  useEffect(() => {
    saveRef.current = doSave;
  }, [doSave]);

  const onMount: OnMount = (editor, monaco) => {
    editorRef.current = editor;
    monacoRef.current = monaco;
    configureMonaco(monaco);
    decorations.current = editor.createDecorationsCollection([]);
    editor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyS, () => saveRef.current());
    const report = () => {
      const pos = editor.getPosition();
      const sel = editor.getSelection();
      const model = editor.getModel();
      if (!pos || !model) return;
      const text = sel && !sel.isEmpty() ? model.getValueInRange(sel) : "";
      setCursor({
        path: pathRef.current,
        line: pos.lineNumber,
        column: pos.column,
        selection: sel && text ? { startLine: sel.startLineNumber, endLine: sel.endLineNumber, text: text.slice(0, 8000) } : null,
      });
    };
    editor.onDidChangeCursorSelection(report);
    editor.onDidFocusEditorText(report);
    setMounted(true);
  };

  // AI-written ranges: violet gutter + tint, with the task in the hover.
  useEffect(() => {
    const monaco = monacoRef.current;
    if (!mounted || !monaco || !decorations.current) return;
    decorations.current.set(
      (file.data?.aiRanges ?? []).map((r) => ({
        range: new monaco.Range(r.startLine, 1, r.endLine, 1),
        options: {
          isWholeLine: true,
          className: "ai-line-bg",
          linesDecorationsClassName: "ai-line-gutter",
          hoverMessage: { value: `Written by AI agent (task \`${r.taskId}\`)` },
          overviewRuler: { color: "#c084fc", position: monaco.editor.OverviewRulerLane.Left },
        },
      })),
    );
  }, [file.data?.aiRanges, mounted, buffer?.baseVersion]);

  // Jump to a position requested by Problems, search or build errors.
  useEffect(() => {
    const ed = editorRef.current;
    if (!mounted || !ed || !reveal || reveal.path !== path) return;
    ed.revealLineInCenter(reveal.line);
    ed.setPosition({ lineNumber: reveal.line, column: reveal.column });
    ed.focus();
  }, [reveal, path, mounted]);

  if (file.isError) return <ErrorState error={file.error} onRetry={() => file.refetch()} />;
  if (file.data?.binary) return <div className="grid h-full place-items-center text-[14px] text-muted-foreground">Binary file — not shown in the editor.</div>;
  if (!buffer) return <EditorLoading />;

  return (
    <div className="flex h-full min-h-0 flex-col">
      {serverChanged ? (
        <Alert tone="warning" className="m-2 mb-0 items-center">
          <AlertTriangle />
          <span className="flex-1">This file changed on the server (possibly by the agent) while you were editing.</span>
          <Button size="sm" variant="outline" onClick={() => { dropBuffer(projectId, path); file.refetch(); }}>
            Discard mine and load latest
          </Button>
        </Alert>
      ) : null}
      <div className="min-h-0 flex-1">
        <Editor
          path={`${projectId}/${path}`}
          language={languageForPath(path)}
          value={buffer.content}
          onChange={(v) => updateBuffer(projectId, path, v ?? "")}
          onMount={onMount}
          options={options}
          theme="apppilot"
          keepCurrentModel
          loading={<EditorLoading />}
        />
      </div>
    </div>
  );
}

/**
 * DiffEditor that disposes its models only after the widget is gone.
 * The stock component disposes models before resetting the widget on
 * unmount, which makes Monaco throw ("TextModel got disposed before
 * DiffEditorWidget model got reset").
 */
function SafeDiffEditor(props: DiffEditorProps) {
  const models = useRef<MonacoEditorNs.IDiffEditorModel | null>(null);
  useEffect(
    () => () => {
      const m = models.current;
      setTimeout(() => {
        m?.original.dispose();
        m?.modified.dispose();
      }, 0);
    },
    [],
  );
  return (
    <DiffEditor
      {...props}
      keepCurrentOriginalModel
      keepCurrentModifiedModel
      onMount={(editor, monaco) => {
        models.current = editor.getModel();
        props.onMount?.(editor, monaco);
      }}
    />
  );
}

/** Side-by-side diff of the saved file and the unsaved buffer. */
export function UnsavedDiff({ projectId, path }: { projectId: string; path: string }) {
  const file = useFile(projectId, path);
  const buffer = useIdeStore((s) => s.buffers[bufferKey(projectId, path)]);
  const options = useEditorOptions(true);
  const monacoRef = useRef<Monaco | null>(null);
  useMonacoTheme(monacoRef);
  if (!file.data || !buffer) return <EditorLoading />;
  return (
    <SafeDiffEditor
      original={file.data.content}
      modified={buffer.content}
      language={languageForPath(path)}
      theme="apppilot"
      options={{ ...options, renderSideBySide: true, originalEditable: false }}
      beforeMount={(m) => {
        monacoRef.current = m;
        configureMonaco(m);
      }}
      loading={<EditorLoading />}
    />
  );
}

export function ReviewDiff({ original, proposed, path }: { original: string; proposed: string; path: string }) {
  const options = useEditorOptions(true);
  const monacoRef = useRef<Monaco | null>(null);
  useMonacoTheme(monacoRef);
  return (
    <SafeDiffEditor
      original={original}
      modified={proposed}
      language={languageForPath(path)}
      theme="apppilot"
      options={{ ...options, renderSideBySide: true }}
      beforeMount={(m) => {
        monacoRef.current = m;
        configureMonaco(m);
      }}
      loading={<EditorLoading />}
    />
  );
}
