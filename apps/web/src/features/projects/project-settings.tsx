"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import type { Project, ProjectEnvVar } from "@apppilot/contracts";
import { KeyRound, Plus, Trash2, X } from "lucide-react";
import { toast } from "sonner";
import { PageBody } from "@/components/layout/page";
import { ErrorState, LoadingRows, QueryView } from "@/components/states/states";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/overlays";
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle, Checkbox, Field, Input, Textarea } from "@/components/ui/primitives";
import { errorMessage } from "@/lib/api/errors";
import { useDeleteProject, useEnvVars, useProject, useUpdateEnvVars, useUpdateProject } from "@/lib/api/hooks";

const PACKAGE_RE = /^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$/;
const ENV_KEY_RE = /^[A-Z_][A-Z0-9_]*$/;

function GeneralForm({ project }: { project: Project }) {
  const update = useUpdateProject(project.id);
  const [name, setName] = useState(project.name);
  const [description, setDescription] = useState(project.description);
  const [pkg, setPkg] = useState(project.packageName ?? "");
  const [minSdk, setMinSdk] = useState(String(project.minSdk ?? ""));
  const [targetSdk, setTargetSdk] = useState(String(project.targetSdk ?? ""));
  const [errors, setErrors] = useState<Record<string, string | undefined>>({});
  const dirty =
    name !== project.name || description !== project.description || pkg !== (project.packageName ?? "") ||
    minSdk !== String(project.minSdk ?? "") || targetSdk !== String(project.targetSdk ?? "");

  const save = (e: React.FormEvent) => {
    e.preventDefault();
    const min = Number(minSdk);
    const target = Number(targetSdk);
    const next = {
      name: !name.trim() ? "Name can't be empty." : undefined,
      pkg: pkg && !PACKAGE_RE.test(pkg) ? "Use a lowercase dotted name like com.example.app." : undefined,
      minSdk: minSdk && (!Number.isInteger(min) || min < 21) ? "Use API 21 or higher." : undefined,
      targetSdk: targetSdk && (!Number.isInteger(target) || target < min) ? "Must be at least the minimum SDK." : undefined,
    };
    setErrors(next);
    if (Object.values(next).some(Boolean)) return;
    update.mutate(
      { name: name.trim(), description, packageName: pkg || undefined, minSdk: min || undefined, targetSdk: target || undefined },
      { onSuccess: () => toast.success("Settings saved"), onError: (err) => toast.error(errorMessage(err)) },
    );
  };

  const readOnlyAndroid = project.isApkAnalysis;

  return (
    <form onSubmit={save}>
      <Card>
        <CardHeader>
          <div>
            <CardTitle>General</CardTitle>
            <CardDescription>Name and Android configuration. Changing the package name or SDK levels asks the agent to update Gradle files.</CardDescription>
          </div>
        </CardHeader>
        <CardContent className="grid gap-4">
          <Field label="Name" htmlFor="p-name" error={errors.name}>
            <Input id="p-name" value={name} onChange={(e) => setName(e.target.value)} aria-invalid={!!errors.name} />
          </Field>
          <Field label="Description" htmlFor="p-desc">
            <Textarea id="p-desc" value={description} onChange={(e) => setDescription(e.target.value)} />
          </Field>
          <div className="grid gap-4 sm:grid-cols-[2fr_1fr_1fr]">
            <Field label="Package name" htmlFor="p-pkg" error={errors.pkg} hint={readOnlyAndroid ? "Read-only for APK analyses." : undefined}>
              <Input id="p-pkg" value={pkg} onChange={(e) => setPkg(e.target.value)} className="font-mono" disabled={readOnlyAndroid} aria-invalid={!!errors.pkg} />
            </Field>
            <Field label="Min SDK" htmlFor="p-min" error={errors.minSdk}>
              <Input id="p-min" inputMode="numeric" value={minSdk} onChange={(e) => setMinSdk(e.target.value)} disabled={readOnlyAndroid} aria-invalid={!!errors.minSdk} />
            </Field>
            <Field label="Target SDK" htmlFor="p-target" error={errors.targetSdk}>
              <Input id="p-target" inputMode="numeric" value={targetSdk} onChange={(e) => setTargetSdk(e.target.value)} disabled={readOnlyAndroid} aria-invalid={!!errors.targetSdk} />
            </Field>
          </div>
        </CardContent>
        <CardFooter className="justify-end">
          <Button type="submit" disabled={!dirty} loading={update.isPending}>
            Save changes
          </Button>
        </CardFooter>
      </Card>
    </form>
  );
}

function EnvVarsForm({ projectId, initial }: { projectId: string; initial: ProjectEnvVar[] }) {
  const update = useUpdateEnvVars(projectId);
  const [rows, setRows] = useState(initial.map((v) => ({ ...v, value: v.value ?? "", existingSecret: v.secret && v.value === null })));
  const keys = rows.map((r) => r.key.trim());
  const invalid = rows.some((r) => r.key && !ENV_KEY_RE.test(r.key)) || new Set(keys.filter(Boolean)).size !== keys.filter(Boolean).length;

  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle>Build environment</CardTitle>
          <CardDescription>Variables available to Gradle during builds. Secret values are write-only: once saved they can be replaced but never shown.</CardDescription>
        </div>
      </CardHeader>
      <CardContent className="grid gap-2">
        {rows.length === 0 ? <p className="text-[14px] text-muted-foreground">No variables yet.</p> : null}
        {rows.map((r, i) => (
          <div key={i} className="grid grid-cols-[1fr_1fr_auto_auto] items-center gap-2">
            <Input aria-label="Variable name" placeholder="MAPS_API_KEY" value={r.key} className="font-mono" aria-invalid={!!r.key && !ENV_KEY_RE.test(r.key)} onChange={(e) => setRows((rs) => rs.map((x, j) => (j === i ? { ...x, key: e.target.value.toUpperCase() } : x)))} />
            <Input
              aria-label="Value"
              type={r.secret ? "password" : "text"}
              placeholder={r.existingSecret ? "•••••• (unchanged)" : "value"}
              value={r.value}
              onChange={(e) => setRows((rs) => rs.map((x, j) => (j === i ? { ...x, value: e.target.value, existingSecret: false } : x)))}
            />
            <label className="flex items-center gap-1.5 text-[13px] text-muted-foreground">
              <Checkbox checked={r.secret} onCheckedChange={(v) => setRows((rs) => rs.map((x, j) => (j === i ? { ...x, secret: v === true } : x)))} />
              <KeyRound className="size-3.5" aria-hidden /> Secret
            </label>
            <Button variant="subtle" size="icon-sm" aria-label={`Remove ${r.key || "variable"}`} onClick={() => setRows((rs) => rs.filter((_, j) => j !== i))}>
              <X />
            </Button>
          </div>
        ))}
        {invalid ? <p className="text-[13px] text-destructive" role="alert">Names must be unique and use A–Z, 0–9 and underscores.</p> : null}
        <Button variant="ghost" size="sm" className="justify-self-start" onClick={() => setRows((rs) => [...rs, { key: "", value: "", secret: false, existingSecret: false }])}>
          <Plus /> Add variable
        </Button>
      </CardContent>
      <CardFooter className="justify-end">
        <Button
          disabled={invalid}
          loading={update.isPending}
          onClick={() =>
            update.mutate(
              rows.filter((r) => r.key.trim()).map((r) => ({ key: r.key.trim(), secret: r.secret, value: r.existingSecret ? null : r.value })),
              { onSuccess: () => toast.success("Environment saved"), onError: (e) => toast.error(errorMessage(e)) },
            )
          }
        >
          Save environment
        </Button>
      </CardFooter>
    </Card>
  );
}

function DangerZone({ project }: { project: Project }) {
  const del = useDeleteProject();
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [typed, setTyped] = useState("");
  return (
    <Card className="border-destructive/40">
      <CardHeader>
        <div>
          <CardTitle>Delete project</CardTitle>
          <CardDescription>Removes files, builds, artifacts, test results and agent history for {project.name}. This can&apos;t be undone.</CardDescription>
        </div>
      </CardHeader>
      <CardFooter className="justify-end border-destructive/20">
        <Button variant="destructive" onClick={() => setOpen(true)}>
          <Trash2 /> Delete project
        </Button>
      </CardFooter>
      <ConfirmDialog
        open={open}
        onOpenChange={(o) => {
          setOpen(o);
          if (!o) setTyped("");
        }}
        title={`Delete ${project.name}?`}
        confirmLabel="Delete project"
        destructive
        loading={del.isPending}
        onConfirm={() => {
          if (typed !== project.name) return;
          del.mutate(project.id, {
            onSuccess: () => {
              toast.success(`Deleted ${project.name}`);
              router.replace("/projects");
            },
            onError: (e) => toast.error(errorMessage(e)),
          });
        }}
      >
        <label className="grid gap-1.5 text-[14px]">
          <span>Type <span className="font-mono">{project.name}</span> to confirm</span>
          <Input value={typed} onChange={(e) => setTyped(e.target.value)} autoFocus />
        </label>
      </ConfirmDialog>
    </Card>
  );
}

export function ProjectSettingsScreen({ projectId }: { projectId: string }) {
  const project = useProject(projectId);
  const env = useEnvVars(projectId);
  if (project.isPending) return <PageBody><LoadingRows rows={6} /></PageBody>;
  if (project.isError) return <PageBody><ErrorState error={project.error} onRetry={() => project.refetch()} /></PageBody>;
  return (
    <PageBody className="grid max-w-3xl gap-6">
      <GeneralForm key={project.data.updatedAt} project={project.data} />
      <QueryView query={env} compact>
        {(vars) => <EnvVarsForm projectId={projectId} initial={vars} />}
      </QueryView>
      <DangerZone project={project.data} />
    </PageBody>
  );
}
