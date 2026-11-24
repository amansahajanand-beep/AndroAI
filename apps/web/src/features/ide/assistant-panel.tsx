"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import type { AgentIntent, ChatMessage, Diagnostic } from "@apppilot/contracts";
import { ArrowUp, Bot, FileCode2, ListChecks, Sparkles, TextSelect, Wrench, X } from "lucide-react";
import { toast } from "sonner";
import { EmptyState, ErrorState, LoadingRows } from "@/components/states/states";
import { AgentStatusBadge, isAgentActive } from "@/components/status/status-badge";
import { Button } from "@/components/ui/button";
import { Select, Tooltip } from "@/components/ui/overlays";
import { Badge, Kbd, Progress, Textarea } from "@/components/ui/primitives";
import { errorMessage, isPendingBackend } from "@/lib/api/errors";
import { useAgentTask, useChangeSet, useDiagnostics, useMessages, useSendMessage } from "@/lib/api/hooks";
import { basename, cn, formatRelative } from "@/lib/utils";
import { isReviewTab, useIdeStore } from "@/stores/ide-store";
import { useTaskStream } from "../agent/use-task-stream";
import { isMod, MOD } from "./shortcuts";

const INTENTS: { value: AgentIntent; label: string; hint: string }[] = [
  { value: "chat", label: "Ask", hint: "Ask a question; no code changes." },
  { value: "explain", label: "Explain code", hint: "Explain the selection or file." },
  { value: "generate", label: "Generate code", hint: "Write new files or features." },
  { value: "modify", label: "Modify code", hint: "Change existing code across files." },
  { value: "fix", label: "Fix errors", hint: "Fix build errors and problems." },
  { value: "refactor", label: "Refactor", hint: "Restructure without changing behaviour." },
];

const PLACEHOLDER: Record<AgentIntent, string> = {
  chat: "Ask about this project…",
  explain: "What should I explain?",
  generate: "Describe what to build, e.g. a settings screen with a dark mode toggle…",
  modify: "Describe the change, e.g. add pull-to-refresh to the trail list…",
  fix: "Describe the problem, or just send to fix current build errors…",
  refactor: "Describe the refactor, e.g. move data access into a repository…",
};

function TaskProgress({ taskId, projectId }: { taskId: string; projectId: string }) {
  const task = useAgentTask(taskId);
  useTaskStream(task.data);
  const t = task.data;
  if (!t) return null;
  const active = isAgentActive(t.status);
  return (
    <div className={cn("mt-2 grid gap-1.5 rounded-xl border p-2.5", active ? "border-ai/30 bg-ai-soft" : "border-border")}>
      <div className="flex items-center justify-between gap-2">
        <AgentStatusBadge status={t.status} />
        <Link href={`/projects/${projectId}/agent?task=${t.id}`} className="text-[12px] text-muted-foreground hover:text-foreground">
          Details
        </Link>
      </div>
      {t.currentStep ? <p className="text-[13px] text-muted-foreground">{t.currentStep}</p> : null}
      {t.buildProgress ? <Progress value={t.buildProgress.percent} tone="ai" label="Build progress" /> : null}
      {t.repairIterations > 0 ? <p className="text-[12px] text-warning">Repair attempt {t.repairIterations} of {t.maxRepairIterations}</p> : null}
      {t.blockedReason ? <p className="text-[13px] text-warning">{t.blockedReason}</p> : null}
      {t.errorMessage ? <p className="text-[13px] text-destructive">{t.errorMessage}</p> : null}
    </div>
  );
}

function ChangeSetCard({ id, projectId }: { id: string; projectId: string }) {
  const cs = useChangeSet(id);
  const openReview = useIdeStore((s) => s.openReview);
  if (!cs.data) return null;
  const pending = cs.data.files.filter((f) => f.decision === "pending").length;
  return (
    <div className="mt-2 rounded-xl border border-ai/30 bg-surface-2/60 p-2.5">
      <div className="flex items-center justify-between gap-2">
        <span className="flex items-center gap-1.5 text-[13px] font-medium">
          <Sparkles className="size-3.5 text-ai" aria-hidden /> {cs.data.files.length} file{cs.data.files.length === 1 ? "" : "s"} changed
        </span>
        {pending === 0 ? (
          <Badge tone={cs.data.status === "applied" ? "success" : "neutral"}>{cs.data.status.replace("_", " ")}</Badge>
        ) : (
          <Badge tone="ai">Waiting for review</Badge>
        )}
      </div>
      <ul className="mt-1.5 grid gap-0.5">
        {cs.data.files.map((f) => (
          <li key={f.path} className="flex items-center gap-1.5 truncate font-mono text-[12px] text-muted-foreground" title={f.path}>
            <span className={cn("w-2.5", { add: "text-git-added", modify: "text-git-modified", delete: "text-git-deleted" }[f.changeType])}>{f.changeType === "add" ? "A" : f.changeType === "delete" ? "D" : "M"}</span>
            {basename(f.path)}
          </li>
        ))}
      </ul>
      <Button size="sm" variant={pending ? "ai" : "outline"} className="mt-2 w-full" onClick={() => openReview(projectId, id)}>
        {pending ? "Review changes" : "View changes"}
      </Button>
    </div>
  );
}

function Message({ m, projectId }: { m: ChatMessage; projectId: string }) {
  if (m.role === "system") return <p className="px-1 text-center text-[12px] text-subtle-foreground">{m.content}</p>;
  const user = m.role === "user";
  return (
    <li className={cn("grid gap-1", user && "justify-items-end")}>
      <div className="flex items-center gap-1.5 text-[12px] text-subtle-foreground">
        {user ? null : <Bot className="size-3.5 text-ai" aria-hidden />}
        <span>{user ? "You" : "Agent"}</span>
        {m.intent && m.intent !== "chat" ? <span>· {INTENTS.find((i) => i.value === m.intent)?.label}</span> : null}
        <time dateTime={m.createdAt}>· {formatRelative(m.createdAt)}</time>
      </div>
      <div className={cn("max-w-full whitespace-pre-wrap break-words text-[14px] leading-relaxed", user ? "rounded-2xl rounded-br-md bg-surface-3 px-3.5 py-2.5" : "bg-transparent px-0.5 py-0.5")}>
        {m.content}
        {m.plan ? (
          <div className="mt-2 rounded-xl border border-border bg-surface-2/50 p-2.5">
            <p className="flex items-center gap-1.5 text-[13px] font-medium"><ListChecks className="size-3.5 text-ai" aria-hidden /> Plan</p>
            {m.plan.summary ? <p className="mt-1 text-[13px] text-muted-foreground">{m.plan.summary}</p> : null}
            <ol className="mt-1.5 grid list-decimal gap-1 pl-4 text-[13px]">
              {m.plan.steps.map((s) => (
                <li key={s.id}>
                  <span className="font-medium">{s.title}</span>
                  {s.detail ? <span className="text-muted-foreground"> — {s.detail}</span> : null}
                  {s.files.length ? <span className="block truncate font-mono text-[12px] text-subtle-foreground">{s.files.map(basename).join(", ")}</span> : null}
                </li>
              ))}
            </ol>
          </div>
        ) : null}
        {m.taskId && !user ? <TaskProgress taskId={m.taskId} projectId={projectId} /> : null}
        {m.changeSetId ? <ChangeSetCard id={m.changeSetId} projectId={projectId} /> : null}
      </div>
    </li>
  );
}

export function AssistantPanel({
  projectId,
  initialIntent,
  isApk,
  onClose,
}: {
  projectId: string;
  initialIntent?: AgentIntent;
  isApk?: boolean;
  onClose: () => void;
}) {
  const messages = useMessages(projectId);
  const send = useSendMessage(projectId);
  const diagnostics = useDiagnostics(projectId);
  const tabs = useIdeStore((s) => s.tabs[projectId]);
  const cursor = useIdeStore((s) => s.cursor);
  const [intent, setIntent] = useState<AgentIntent>(initialIntent ?? "modify");
  const [prompt, setPrompt] = useState("");
  const [useSelection, setUseSelection] = useState(true);
  const [useFile, setUseFile] = useState(true);
  const listRef = useRef<HTMLDivElement>(null);

  const activeFile = tabs?.active && !isReviewTab(tabs.active) ? tabs.active : null;
  const selection = cursor && cursor.path === activeFile ? cursor.selection : null;
  const errors = (diagnostics.data ?? []).filter((d: Diagnostic) => d.severity === "error");

  useEffect(() => {
    const el = listRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages.data?.length, send.isPending]);

  const submit = (override?: { intent: AgentIntent; prompt: string }) => {
    const i = override?.intent ?? intent;
    const text = (override?.prompt ?? prompt).trim() || (i === "fix" && errors.length ? "Fix the current build errors." : "");
    if (!text) return;
    send.mutate(
      {
        intent: i,
        prompt: text,
        context: {
          activeFile: useFile && activeFile ? activeFile : undefined,
          selection: useSelection && selection ? selection : undefined,
          openFiles: tabs?.openTabs.filter((t) => !isReviewTab(t)),
          diagnostics: i === "fix" ? errors.map((d) => ({ path: d.path, line: d.line, message: d.message })) : undefined,
        },
      },
      {
        onSuccess: () => {
          if (!override) setPrompt("");
        },
        onError: (e) => toast.error(isPendingBackend(e) ? "The agent service isn't available yet — its endpoint is pending." : errorMessage(e)),
      },
    );
  };

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex h-10 shrink-0 items-center justify-between border-b border-border pl-3.5 pr-2">
        <h2 className="flex items-center gap-1.5 text-[13px] font-semibold text-foreground">
          <Sparkles className="size-3.5 text-ai" aria-hidden /> AI assistant
        </h2>
        <Tooltip content="Hide assistant" shortcut={`${MOD}+Alt+B`}>
          <Button variant="subtle" size="icon-xs" aria-label="Hide assistant" onClick={onClose}>
            <X />
          </Button>
        </Tooltip>
      </div>

      <div ref={listRef} className="min-h-0 flex-1 overflow-y-auto px-3 py-3">
        {messages.isPending ? (
          <LoadingRows rows={4} />
        ) : messages.isError ? (
          <ErrorState error={messages.error} onRetry={() => messages.refetch()} compact />
        ) : messages.data.length === 0 ? (
          <EmptyState compact icon={<Bot />} title="Ask the agent to change this project">
            It plans the work, edits files, runs a build and hands the changes back for your review.
          </EmptyState>
        ) : (
          <ol className="grid gap-4" aria-label="Conversation" aria-live="polite">
            {messages.data.map((m) => (
              <Message key={m.id} m={m} projectId={projectId} />
            ))}
          </ol>
        )}
      </div>

      <div className="shrink-0 border-t border-border p-2">
        {isApk ? (
          <p className="mb-2 rounded-lg bg-warning-soft px-2.5 py-1.5 text-[12px] text-warning">
            APK analysis: the agent can explain decompiled code, but changes produce new code rather than editing the original app.
          </p>
        ) : null}
        <div className="mb-2 flex flex-wrap gap-1.5">
          <Button variant="outline" size="sm" className="h-7 rounded-full px-2.5 text-[12px]" disabled={!selection || send.isPending} onClick={() => submit({ intent: "explain", prompt: "Explain the selected code." })}>
            <TextSelect /> Explain selection
          </Button>
          <Button variant="outline" size="sm" className="h-7 rounded-full px-2.5 text-[12px]" disabled={!errors.length || send.isPending} onClick={() => submit({ intent: "fix", prompt: `Fix the ${errors.length} build error${errors.length === 1 ? "" : "s"}.` })}>
            <Wrench /> Fix {errors.length || ""} error{errors.length === 1 ? "" : "s"}
          </Button>
          <Button variant="outline" size="sm" className="h-7 rounded-full px-2.5 text-[12px]" disabled={!activeFile || send.isPending} onClick={() => submit({ intent: "refactor", prompt: `Refactor ${activeFile ? basename(activeFile) : "this file"} for readability without changing behaviour.` })}>
            Refactor file
          </Button>
        </div>
        <div className="mb-1.5 flex flex-wrap gap-1">
          {activeFile ? (
            <button
              onClick={() => setUseFile((v) => !v)}
              aria-pressed={useFile}
              className={cn("inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 font-mono text-[12px] transition-colors", useFile ? "border-border-strong text-foreground" : "border-dashed border-border text-subtle-foreground line-through")}
              title={useFile ? "Active file is included as context. Click to exclude." : "Click to include the active file."}
            >
              <FileCode2 className="size-3" aria-hidden /> {basename(activeFile)}
            </button>
          ) : null}
          {selection ? (
            <button
              onClick={() => setUseSelection((v) => !v)}
              aria-pressed={useSelection}
              className={cn("inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 font-mono text-[12px] transition-colors", useSelection ? "border-border-strong text-foreground" : "border-dashed border-border text-subtle-foreground line-through")}
            >
              <TextSelect className="size-3" aria-hidden /> lines {selection.startLine}–{selection.endLine}
            </button>
          ) : null}
        </div>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            submit();
          }}
          className="rounded-2xl border border-border-strong bg-surface-2/70 transition-colors focus-within:border-ring/70"
        >
          <label htmlFor="assistant-prompt" className="sr-only">Message the agent</label>
          <Textarea
            id="assistant-prompt"
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && (isMod(e) || !e.shiftKey)) {
                e.preventDefault();
                submit();
              }
            }}
            placeholder={PLACEHOLDER[intent]}
            className="min-h-16 resize-none border-0 bg-transparent px-3.5 pt-3 hover:border-0 focus-visible:outline-none focus-visible:ring-0"
          />
          <div className="flex items-center justify-between gap-2 px-2 pb-2">
            <Select<AgentIntent> aria-label="What should the agent do?" value={intent} onValueChange={setIntent} options={INTENTS} className="h-8 w-36 rounded-full border-border-strong bg-transparent text-[13px]" />
            <span className="flex items-center gap-2">
              <span className="hidden text-[12px] text-subtle-foreground xl:inline"><Kbd>Enter</Kbd> to send</span>
              <Button type="submit" size="icon-sm" variant="ai" className="rounded-full" aria-label="Send" loading={send.isPending} disabled={!prompt.trim() && !(intent === "fix" && errors.length)}>
                {send.isPending ? null : <ArrowUp />}
              </Button>
            </span>
          </div>
        </form>
      </div>
    </div>
  );
}
