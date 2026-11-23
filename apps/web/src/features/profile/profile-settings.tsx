"use client";

import { useTheme } from "next-themes";
import { useState } from "react";
import type { User, UserPreferences } from "@apppilot/contracts";
import { toast } from "sonner";
import { PageBody, PageHeader } from "@/components/layout/page";
import { EmptyState, QueryView } from "@/components/states/states";
import { Button } from "@/components/ui/button";
import { Segmented, Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/overlays";
import { Avatar, Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle, Field, Input, Switch } from "@/components/ui/primitives";
import { errorMessage } from "@/lib/api/errors";
import { useApiKeys, useChangePassword, usePreferences, useSession, useUpdatePreferences, useUpdateProfile } from "@/lib/api/hooks";
import { formatRelative } from "@/lib/utils";
import { useEditorSettings } from "@/stores/editor-settings";

function ProfileCard({ user }: { user: User }) {
  const update = useUpdateProfile();
  const [name, setName] = useState(user.name);
  return (
    <Card>
      <CardHeader><div><CardTitle>Profile</CardTitle><CardDescription>Shown on commits you make in the IDE.</CardDescription></div></CardHeader>
      <CardContent className="grid gap-4">
        <div className="flex items-center gap-3">
          <Avatar name={user.name} src={user.avatarUrl} className="size-10" />
          <div className="text-[14px]">
            <p className="font-medium">{user.email}</p>
            <p className="text-[13px] text-muted-foreground">{user.emailVerified ? "Verified" : "Not verified — check your inbox"} · {user.role === "admin" ? "Admin" : "Member"}</p>
          </div>
        </div>
        <Field label="Name" htmlFor="u-name">
          <Input id="u-name" value={name} onChange={(e) => setName(e.target.value)} />
        </Field>
      </CardContent>
      <CardFooter className="justify-end">
        <Button disabled={!name.trim() || name === user.name} loading={update.isPending} onClick={() => update.mutate({ name: name.trim() }, { onSuccess: () => toast.success("Profile saved"), onError: (e) => toast.error(errorMessage(e)) })}>
          Save profile
        </Button>
      </CardFooter>
    </Card>
  );
}

function PasswordCard() {
  const change = useChangePassword();
  const [cur, setCur] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const err = next && next.length < 10 ? "Use at least 10 characters." : confirm && confirm !== next ? "Passwords don't match." : undefined;
  return (
    <Card>
      <CardHeader><div><CardTitle>Password</CardTitle></div></CardHeader>
      <CardContent className="grid gap-4 sm:grid-cols-3">
        <Field label="Current password" htmlFor="pw-cur"><Input id="pw-cur" type="password" autoComplete="current-password" value={cur} onChange={(e) => setCur(e.target.value)} /></Field>
        <Field label="New password" htmlFor="pw-new"><Input id="pw-new" type="password" autoComplete="new-password" value={next} onChange={(e) => setNext(e.target.value)} /></Field>
        <Field label="Confirm new password" htmlFor="pw-confirm" error={err}><Input id="pw-confirm" type="password" autoComplete="new-password" value={confirm} onChange={(e) => setConfirm(e.target.value)} /></Field>
      </CardContent>
      <CardFooter className="justify-end">
        <Button
          disabled={!cur || !next || next !== confirm || !!err}
          loading={change.isPending}
          onClick={() => change.mutate({ currentPassword: cur, newPassword: next }, {
            onSuccess: () => { toast.success("Password changed"); setCur(""); setNext(""); setConfirm(""); },
            onError: (e) => toast.error(errorMessage(e)),
          })}
        >
          Change password
        </Button>
      </CardFooter>
    </Card>
  );
}

function PreferencesCard({ prefs }: { prefs: UserPreferences }) {
  const save = useUpdatePreferences();
  const { setTheme } = useTheme();
  const [p, setP] = useState(prefs);
  const notif = (k: keyof UserPreferences["emailNotifications"], label: string) => (
    <label className="flex items-center justify-between gap-3 text-[14px]">
      {label}
      <Switch checked={p.emailNotifications[k]} onCheckedChange={(v) => setP({ ...p, emailNotifications: { ...p.emailNotifications, [k]: v } })} />
    </label>
  );
  return (
    <Card>
      <CardHeader><div><CardTitle>Preferences</CardTitle><CardDescription>Synced to your account across devices.</CardDescription></div></CardHeader>
      <CardContent className="grid gap-5">
        <div className="grid gap-1.5"><span className="text-[14px] font-medium">Theme</span>
          <Segmented aria-label="Theme" value={p.theme} onChange={(theme) => { setP({ ...p, theme }); setTheme(theme); }} options={[{ value: "dark", label: "Dark" }, { value: "light", label: "Light" }, { value: "system", label: "System" }]} />
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="grid gap-1.5"><span className="text-[14px] font-medium">Default language for new apps</span>
            <Segmented aria-label="Default language" value={p.defaultLanguage} onChange={(defaultLanguage) => setP({ ...p, defaultLanguage })} options={[{ value: "kotlin", label: "Kotlin" }, { value: "java", label: "Java" }]} />
          </div>
          <div className="grid gap-1.5"><span className="text-[14px] font-medium">Default UI toolkit</span>
            <Segmented aria-label="Default UI toolkit" value={p.defaultUiToolkit} onChange={(defaultUiToolkit) => setP({ ...p, defaultUiToolkit })} options={[{ value: "compose", label: "Compose" }, { value: "xml", label: "XML views" }]} />
          </div>
        </div>
        <fieldset className="grid gap-2.5">
          <legend className="mb-2 text-[14px] font-medium">Email me when</legend>
          {notif("buildFailed", "A build fails")}
          {notif("agentTaskCompleted", "An agent task finishes or needs input")}
          {notif("usageThreshold", "Usage passes 80% of a plan limit")}
        </fieldset>
      </CardContent>
      <CardFooter className="justify-end">
        <Button loading={save.isPending} onClick={() => save.mutate(p, { onSuccess: () => toast.success("Preferences saved"), onError: (e) => toast.error(errorMessage(e)) })}>Save preferences</Button>
      </CardFooter>
    </Card>
  );
}

function EditorCard() {
  const s = useEditorSettings();
  return (
    <Card>
      <CardHeader><div><CardTitle>Editor</CardTitle><CardDescription>Stored in this browser and applied immediately.</CardDescription></div></CardHeader>
      <CardContent className="grid gap-4">
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Font size" htmlFor="ed-font">
            <Input id="ed-font" type="number" min={10} max={24} value={s.fontSize} onChange={(e) => s.set({ fontSize: Math.min(24, Math.max(10, Number(e.target.value) || 13)) })} />
          </Field>
          <div className="grid gap-1.5"><span className="text-[14px] font-medium">Tab size</span>
            <Segmented aria-label="Tab size" value={String(s.tabSize) as "2" | "4"} onChange={(v) => s.set({ tabSize: v === "2" ? 2 : 4 })} options={[{ value: "2", label: "2 spaces" }, { value: "4", label: "4 spaces" }]} />
          </div>
        </div>
        {([["wordWrap", "Word wrap"], ["minimap", "Minimap"], ["lineNumbers", "Line numbers"]] as const).map(([k, label]) => (
          <label key={k} className="flex items-center justify-between text-[14px]">{label}<Switch checked={s[k]} onCheckedChange={(v) => s.set({ [k]: v })} /></label>
        ))}
      </CardContent>
      <CardFooter className="justify-end"><Button variant="outline" onClick={s.reset}>Reset to defaults</Button></CardFooter>
    </Card>
  );
}

function ApiKeysCard() {
  const keys = useApiKeys();
  return (
    <Card>
      <CardHeader><div><CardTitle>API keys</CardTitle><CardDescription>For CI and scripts. A key&apos;s secret is shown once, when it&apos;s created.</CardDescription></div></CardHeader>
      <QueryView query={keys} compact isEmpty={(d) => d.length === 0} empty={<EmptyState compact title="No API keys" />}>
        {(list) => (
          <ul className="divide-y divide-border border-t border-border">
            {list.map((k) => (
              <li key={k.id} className="flex items-center justify-between gap-3 px-5 py-2.5 text-[14px]">
                <span><span className="font-medium">{k.name}</span> <span className="font-mono text-[13px] text-muted-foreground">…{k.lastFour}</span></span>
                <span className="text-[13px] text-muted-foreground">Last used {formatRelative(k.lastUsedAt)}</span>
              </li>
            ))}
          </ul>
        )}
      </QueryView>
    </Card>
  );
}

export function ProfileSettingsScreen() {
  const session = useSession();
  const prefs = usePreferences();
  return (
    <PageBody className="max-w-3xl">
      <PageHeader title="Settings" />
      <Tabs defaultValue="account">
        <TabsList className="mb-5">
          <TabsTrigger value="account">Account</TabsTrigger>
          <TabsTrigger value="preferences">Preferences</TabsTrigger>
          <TabsTrigger value="editor">Editor</TabsTrigger>
          <TabsTrigger value="api">API keys</TabsTrigger>
        </TabsList>
        <TabsContent value="account" className="grid gap-6">
          {session.data ? <ProfileCard user={session.data.user} /> : null}
          <PasswordCard />
        </TabsContent>
        <TabsContent value="preferences">
          <QueryView query={prefs}>{(p) => <PreferencesCard prefs={p} />}</QueryView>
        </TabsContent>
        <TabsContent value="editor"><EditorCard /></TabsContent>
        <TabsContent value="api"><ApiKeysCard /></TabsContent>
      </Tabs>
    </PageBody>
  );
}
