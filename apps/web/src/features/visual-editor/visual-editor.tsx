"use client";

import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";
import type { UiEdit, UiNode, UiScreen } from "@apppilot/contracts";
import { ChevronRight, MousePointerSquareDashed, Redo2, Sparkles, Undo2 } from "lucide-react";
import { toast } from "sonner";
import { PageBody } from "@/components/layout/page";
import { EmptyState, ErrorState, LoadingRows, PendingBackend } from "@/components/states/states";
import { Button } from "@/components/ui/button";
import { Card, Input, Label, Textarea } from "@/components/ui/primitives";
import { api } from "@/lib/api/client";
import { errorMessage, isPendingBackend } from "@/lib/api/errors";
import { useUiScreens } from "@/lib/api/hooks";
import { cn } from "@/lib/utils";
import { useIdeStore } from "@/stores/ide-store";

/**
 * Visual UI editor. Every edit is sent to the code-generation backend, which
 * rewrites the Compose/XML source and returns a change set for review.
 * There is deliberately no local-only preview mutation.
 */

function findNode(root: UiNode, id: string | null): UiNode | null {
  if (!id) return null;
  if (root.id === id) return root;
  for (const c of root.children) {
    const hit = findNode(c, id);
    if (hit) return hit;
  }
  return null;
}

function Tree({ node, selected, onSelect, depth = 0 }: { node: UiNode; selected: string | null; onSelect: (id: string) => void; depth?: number }) {
  return (
    <li>
      <button
        onClick={() => onSelect(node.id)}
        className={cn("flex h-8 w-full items-center gap-1 rounded-md pr-2 text-left font-mono text-[13px] transition-colors hover:bg-surface-2", selected === node.id && "bg-surface-3 text-foreground")}
        style={{ paddingLeft: 6 + depth * 12 }}
      >
        {node.children.length ? <ChevronRight className="size-3 rotate-90 text-subtle-foreground" aria-hidden /> : <span className="w-3" />}
        {node.component}
      </button>
      {node.children.length ? (
        <ul>
          {node.children.map((c) => (
            <Tree key={c.id} node={c} selected={selected} onSelect={onSelect} depth={depth + 1} />
          ))}
        </ul>
      ) : null}
    </li>
  );
}

const PROP_GROUPS: { title: string; match: RegExp }[] = [
  { title: "Text and typography", match: /text|font|style|letter|line/i },
  { title: "Colour", match: /color|colour|background|tint/i },
  { title: "Spacing", match: /padding|margin|spacing/i },
  { title: "Alignment", match: /align|arrangement|gravity/i },
];

function Inspector({ node, onEdit, busy }: { node: UiNode; onEdit: (e: UiEdit) => void; busy: boolean }) {
  const [draft, setDraft] = useState<Record<string, string>>({});
  const entries = Object.entries(node.props);
  const grouped = PROP_GROUPS.map((g) => ({ ...g, props: entries.filter(([k]) => g.match.test(k)) }));
  const other = entries.filter(([k]) => !PROP_GROUPS.some((g) => g.match.test(k)));

  const field = ([k, v]: [string, unknown]) => (
    <div key={k} className="grid grid-cols-[110px_1fr] items-center gap-2">
      <Label htmlFor={`prop-${k}`} className="truncate font-mono text-[13px] font-normal text-muted-foreground">{k}</Label>
      <Input
        id={`prop-${k}`}
        className="h-7 font-mono text-[13px]"
        value={draft[k] ?? String(v ?? "")}
        onChange={(e) => setDraft((d) => ({ ...d, [k]: e.target.value }))}
        onBlur={() => {
          if (draft[k] !== undefined && draft[k] !== String(v ?? "")) onEdit({ kind: "setProp", nodeId: node.id, prop: k, value: draft[k] });
        }}
        disabled={busy}
      />
    </div>
  );

  return (
    <div className="grid gap-4">
      <p className="font-mono text-[13px] text-muted-foreground">
        {node.source.path}:{node.source.startLine}
      </p>
      {[...grouped, { title: "Other", props: other }].filter((g) => g.props.length).map((g) => (
        <section key={g.title} className="grid gap-1.5">
          <h3 className="text-[13px] font-semibold">{g.title}</h3>
          {g.props.map(field)}
        </section>
      ))}
      {entries.length === 0 ? <p className="text-[13px] text-muted-foreground">No editable properties.</p> : null}
    </div>
  );
}

function Editor({ projectId, screens }: { projectId: string; screens: UiScreen[] }) {
  const router = useRouter();
  const openReview = useIdeStore((s) => s.openReview);
  const [screenId, setScreenId] = useState(screens[0]?.id ?? null);
  const [current, setCurrent] = useState<UiScreen | null>(screens[0] ?? null);
  const [selected, setSelected] = useState<string | null>(null);
  const [history, setHistory] = useState<{ past: UiEdit[][]; future: UiEdit[][] }>({ past: [], future: [] });
  const [prompt, setPrompt] = useState("");
  const [busy, setBusy] = useState(false);
  const node = useMemo(() => (current ? findNode(current.root, selected) : null), [current, selected]);

  const apply = async (edits: UiEdit[], record = true) => {
    if (!current) return;
    setBusy(true);
    try {
      const res = await api.ui.applyEdits(projectId, current.id, { edits });
      setCurrent(res.screen);
      if (record) setHistory((h) => ({ past: [...h.past, edits], future: [] }));
      toast.success("Change ready for review", {
        action: { label: "Review", onClick: () => { openReview(projectId, res.changeSet.id); router.push(`/projects/${projectId}/ide`); } },
      });
    } catch (e) {
      toast.error(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="grid gap-4 lg:grid-cols-[220px_minmax(0,1fr)_300px]">
      <Card className="p-2">
        <h2 className="px-1 pb-2 text-[13px] font-semibold text-muted-foreground">Screens</h2>
        <ul className="grid gap-0.5">
          {screens.map((s) => (
            <li key={s.id}>
              <button
                onClick={async () => {
                  setScreenId(s.id);
                  setSelected(null);
                  setCurrent(await api.ui.screen(projectId, s.id).catch(() => s));
                }}
                className={cn("w-full truncate rounded-sm px-2 py-1.5 text-left text-[14px] hover:bg-surface-2", screenId === s.id && "bg-surface-3")}
              >
                {s.name}
              </button>
            </li>
          ))}
        </ul>
        {current ? (
          <>
            <h2 className="mt-4 px-1 pb-2 text-[13px] font-semibold text-muted-foreground">Components</h2>
            <ul>
              <Tree node={current.root} selected={selected} onSelect={setSelected} />
            </ul>
          </>
        ) : null}
      </Card>

      <Card className="flex flex-col items-center gap-3 p-5">
        <div className="flex w-full items-center justify-between">
          <span className="text-[14px] font-medium">{current?.name ?? "Preview"}</span>
          <span className="flex gap-1">
            <Button variant="subtle" size="icon-sm" aria-label="Undo" disabled={!history.past.length || busy} onClick={() => setHistory((h) => ({ past: h.past.slice(0, -1), future: [h.past[h.past.length - 1]!, ...h.future] }))}>
              <Undo2 />
            </Button>
            <Button variant="subtle" size="icon-sm" aria-label="Redo" disabled={!history.future.length || busy} onClick={() => { const [next, ...rest] = history.future; if (next) { setHistory((h) => ({ ...h, future: rest })); apply(next); } }}>
              <Redo2 />
            </Button>
          </span>
        </div>
        <div className="flex aspect-[9/19] w-full max-w-[300px] items-center justify-center overflow-hidden rounded-[22px] border-4 border-surface-3 bg-background">
          {current?.previewUrl ? (
            // eslint-disable-next-line @next/next/no-img-element -- backend-rendered preview image
            <img src={current.previewUrl} alt={`Preview of ${current.name}`} className="size-full object-cover" />
          ) : (
            <p className="px-6 text-center text-[13px] text-muted-foreground">The backend hasn&apos;t rendered a preview for this screen yet.</p>
          )}
        </div>
        <p className="text-center text-[13px] text-muted-foreground">
          Undo records your edit history here; to revert code, reject the change set in review.
        </p>
      </Card>

      <Card className="grid min-w-0 grid-cols-[minmax(0,1fr)] content-start gap-4 p-5">
        {node ? <Inspector key={node.id} node={node} busy={busy} onEdit={(e) => apply([e])} /> : <p className="text-[14px] text-muted-foreground">Select a component to edit its properties.</p>}
        <form
          className="grid gap-2 border-t border-border pt-4"
          onSubmit={(e) => {
            e.preventDefault();
            if (!prompt.trim()) return;
            apply([{ kind: "prompt", nodeId: selected, instruction: prompt.trim() }]);
            setPrompt("");
          }}
        >
          <Label htmlFor="ve-prompt" className="flex items-center gap-1.5"><Sparkles className="size-3.5 text-ai" aria-hidden /> Ask the agent</Label>
          <Textarea id="ve-prompt" value={prompt} onChange={(e) => setPrompt(e.target.value)} placeholder={node ? `Change the ${node.component}…` : "Make the list items more compact…"} className="min-h-16" />
          <Button type="submit" variant="ai" size="sm" loading={busy} disabled={!prompt.trim()}>
            Propose change
          </Button>
        </form>
      </Card>
    </div>
  );
}

export function VisualEditorScreen({ projectId }: { projectId: string }) {
  const screens = useUiScreens(projectId);
  return (
    <PageBody>
      <p className="mb-5 max-w-prose text-[14px] text-muted-foreground">
        Select a component, change its properties or describe a change. Edits arrive as a reviewable diff.
      </p>
      {screens.isPending ? (
        <LoadingRows rows={6} />
      ) : screens.isError ? (
        isPendingBackend(screens.error) ? (
          <Card>
            <PendingBackend endpoint="ui.screens">
              The visual editor needs the code-generation service to parse screens into a component tree and render
              previews. It becomes available as soon as that service is connected.
            </PendingBackend>
          </Card>
        ) : (
          <ErrorState error={screens.error} onRetry={() => screens.refetch()} />
        )
      ) : screens.data.length === 0 ? (
        <Card><EmptyState icon={<MousePointerSquareDashed />} title="No screens found">The parser didn&apos;t find any Compose screens or XML layouts in this project.</EmptyState></Card>
      ) : (
        <Editor projectId={projectId} screens={screens.data} />
      )}
    </PageBody>
  );
}
