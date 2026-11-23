"use client";

import { useState } from "react";
import type { ChangeSet, FileChange } from "@apppilot/contracts";
import { CheckCheck, FileMinus, FilePen, FilePlus, Sparkles, X } from "lucide-react";
import { toast } from "sonner";
import { ErrorState, LoadingRows } from "@/components/states/states";
import { Button } from "@/components/ui/button";
import { Alert, Badge, Checkbox } from "@/components/ui/primitives";
import { errorMessage } from "@/lib/api/errors";
import { useChangeSet, useDecideChangeSet } from "@/lib/api/hooks";
import { cn } from "@/lib/utils";
import { ReviewDiff } from "./code-editor";

const CHANGE_META = {
  add: { icon: FilePlus, label: "Added", tone: "success" as const },
  modify: { icon: FilePen, label: "Modified", tone: "warning" as const },
  delete: { icon: FileMinus, label: "Deleted", tone: "danger" as const },
};

function lineDelta(f: FileChange) {
  const a = f.originalContent?.split("\n") ?? [];
  const b = f.proposedContent?.split("\n") ?? [];
  const setA = new Set(a);
  const setB = new Set(b);
  return { plus: b.filter((l) => !setA.has(l)).length, minus: a.filter((l) => !setB.has(l)).length };
}

function Review({ cs, projectId }: { cs: ChangeSet; projectId: string }) {
  const decide = useDecideChangeSet(projectId);
  const pending = cs.files.filter((f) => f.decision === "pending");
  const [checked, setChecked] = useState<Set<string>>(() => new Set(pending.map((f) => f.path)));
  const [active, setActive] = useState(cs.files[0]?.path ?? null);
  const current = cs.files.find((f) => f.path === active);
  const decided = pending.length === 0;

  const submit = (acceptPaths: string[]) =>
    decide.mutate(
      { id: cs.id, acceptPaths },
      {
        onSuccess: (res) => {
          const n = res.files.filter((f) => f.decision === "accepted").length;
          toast.success(n ? `Applied ${n} of ${res.files.length} file${res.files.length === 1 ? "" : "s"}` : "Changes rejected");
        },
        onError: (e) => toast.error(errorMessage(e)),
      },
    );

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex flex-wrap items-center gap-3 border-b border-border px-3 py-2">
        <Sparkles className="size-4 text-ai" aria-hidden />
        <p className="min-w-0 flex-1 truncate text-[14px]">{cs.summary}</p>
        {decided ? (
          <Badge tone={cs.status === "applied" ? "success" : cs.status === "rejected" ? "neutral" : "warning"}>
            {cs.status === "applied" ? "Applied" : cs.status === "rejected" ? "Rejected" : "Partially applied"}
          </Badge>
        ) : (
          <div className="flex gap-2">
            <Button size="sm" variant="outline" disabled={decide.isPending} onClick={() => submit([])}>
              <X /> Reject all
            </Button>
            <Button size="sm" variant="ai" loading={decide.isPending} disabled={checked.size === 0} onClick={() => submit([...checked])}>
              <CheckCheck /> {checked.size === pending.length ? `Accept all ${pending.length}` : `Accept ${checked.size} selected`}
            </Button>
          </div>
        )}
      </div>
      {!decided ? (
        <p className="border-b border-border px-3 py-1.5 text-[13px] text-muted-foreground">
          Nothing is written to your project until you accept. Unchecked files are rejected.
        </p>
      ) : null}
      <div className="flex min-h-0 flex-1">
        <ul className="w-64 shrink-0 overflow-y-auto border-r border-border py-1" aria-label="Changed files">
          {cs.files.map((f) => {
            const m = CHANGE_META[f.changeType];
            const d = lineDelta(f);
            return (
              <li key={f.path} className={cn("flex items-center gap-2 px-2 py-1.5", active === f.path && "bg-surface-2")}>
                {f.decision === "pending" ? (
                  <Checkbox
                    aria-label={`Accept ${f.path}`}
                    checked={checked.has(f.path)}
                    onCheckedChange={(v) =>
                      setChecked((s) => {
                        const n = new Set(s);
                        if (v) n.add(f.path);
                        else n.delete(f.path);
                        return n;
                      })
                    }
                  />
                ) : (
                  <Badge tone={f.decision === "accepted" ? "success" : "neutral"} className="px-1">{f.decision === "accepted" ? "✓" : "✕"}</Badge>
                )}
                <button className="min-w-0 flex-1 text-left" onClick={() => setActive(f.path)} title={f.path}>
                  <span className="flex items-center gap-1.5">
                    <m.icon className={cn("size-3.5 shrink-0", { success: "text-git-added", warning: "text-git-modified", danger: "text-git-deleted" }[m.tone])} aria-label={m.label} />
                    <span className="truncate font-mono text-[13px]">{f.path.split("/").pop()}</span>
                  </span>
                  <span className="block truncate pl-5 text-[12px] text-subtle-foreground">
                    <span className="text-git-added">+{d.plus}</span> <span className="text-git-deleted">−{d.minus}</span> · {f.path.split("/").slice(0, -1).join("/")}
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
        <div className="min-w-0 flex-1">
          {current ? (
            <ReviewDiff key={current.path} path={current.path} original={current.originalContent ?? ""} proposed={current.proposedContent ?? ""} />
          ) : null}
        </div>
      </div>
    </div>
  );
}

export function ChangeReview({ changeSetId, projectId }: { changeSetId: string; projectId: string }) {
  const cs = useChangeSet(changeSetId);
  if (cs.isPending) return <LoadingRows rows={6} />;
  if (cs.isError) return <ErrorState error={cs.error} onRetry={() => cs.refetch()} />;
  if (cs.data.files.length === 0)
    return (
      <Alert tone="info" className="m-3">
        <Sparkles />
        <span>This change set has no file changes.</span>
      </Alert>
    );
  return <Review key={cs.data.id} cs={cs.data} projectId={projectId} />;
}
