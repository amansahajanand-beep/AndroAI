"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";
import { Eye, EyeOff, Lock, Mail, MailCheck, UserRound, type LucideIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Alert, Checkbox, Field, Input } from "@/components/ui/primitives";
import { ApiError, errorMessage, isPendingBackend } from "@/lib/api/errors";
import { useForgotPassword, useLogin, useRegister, useResetPassword, useSession } from "@/lib/api/hooks";
import { cn } from "@/lib/utils";

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const MIN_PASSWORD = 10;

type Errors = Record<string, string | undefined>;

function serverFieldErrors(err: unknown): Errors {
  return err instanceof ApiError && err.fields ? err.fields : {};
}

/** Client-side errors take precedence, but an `undefined` entry must not hide a server field error. */
function mergeErrors(server: Errors, local: Errors): Errors {
  return { ...server, ...Object.fromEntries(Object.entries(local).filter(([, v]) => v)) };
}

function FormError({ error }: { error: unknown }) {
  if (!error) return null;
  return (
    <Alert tone="danger" role="alert">
      <span>
        {isPendingBackend(error)
          ? "The sign-in service isn't reachable right now. Try again in a moment."
          : errorMessage(error)}
      </span>
    </Alert>
  );
}

/** Only allow same-site relative redirects after sign-in. */
/** Where a successful sign-in always lands. */
const AFTER_LOGIN = "/dashboard";

/* Presentational helpers for the Sign in / Register screens (no auth logic). */

const AUTH_INPUT =
  "h-11 rounded-lg border-border-strong bg-surface pl-10 text-[15px] transition-[border-color,box-shadow] duration-200 hover:border-primary/50 focus-visible:border-primary focus-visible:shadow-[0_0_0_4px_var(--primary-soft)]";
const AUTH_BUTTON =
  "h-11 w-full rounded-lg text-[15px] transition-all duration-200 hover:shadow-[0_10px_28px_-12px_var(--primary)] active:translate-y-px";
const AUTH_LINK = "font-medium text-primary underline-offset-4 transition-colors hover:underline";

function IconInput({ icon: Icon, className, ...props }: React.ComponentProps<typeof Input> & { icon: LucideIcon }) {
  return (
    <div className="group relative">
      <Icon
        className="pointer-events-none absolute left-3.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground transition-colors group-focus-within:text-primary"
        aria-hidden
      />
      <Input className={cn(AUTH_INPUT, className)} {...props} />
    </div>
  );
}

function PasswordInput({ className, ...props }: Omit<React.ComponentProps<typeof Input>, "type">) {
  const [show, setShow] = useState(false);
  return (
    <div className="group relative">
      <Lock
        className="pointer-events-none absolute left-3.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground transition-colors group-focus-within:text-primary"
        aria-hidden
      />
      <Input type={show ? "text" : "password"} className={cn(AUTH_INPUT, "pr-11", className)} {...props} />
      <button
        type="button"
        onClick={() => setShow((s) => !s)}
        aria-label={show ? "Hide password" : "Show password"}
        aria-pressed={show}
        className="absolute right-1.5 top-1/2 grid size-8 -translate-y-1/2 place-items-center rounded-md text-muted-foreground transition-colors hover:bg-surface-2 hover:text-foreground"
      >
        {show ? <EyeOff className="size-4" aria-hidden /> : <Eye className="size-4" aria-hidden />}
      </button>
    </div>
  );
}

function AuthHeading({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="mb-1">
      <h1 className="text-balance text-[1.75rem] font-semibold leading-tight tracking-[-0.02em]">{title}</h1>
      <p className="mt-2 text-[14.5px] leading-relaxed text-muted-foreground">{children}</p>
    </div>
  );
}

export function LoginForm() {
  const router = useRouter();
  const login = useLogin();
  const session = useSession();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [remember, setRemember] = useState(true);
  const [errors, setErrors] = useState<Errors>({});

  // Already signed in (for example after a refresh on /login): go straight to the dashboard.
  useEffect(() => {
    if (session.data) router.replace(AFTER_LOGIN);
  }, [session.data, router]);

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const next: Errors = {
      email: !EMAIL_RE.test(email) ? "Enter a valid email address." : undefined,
      password: !password ? "Enter your password." : undefined,
    };
    setErrors(next);
    if (next.email || next.password) return;
    login.mutate(
      { email, password, remember },
      { onSuccess: () => router.replace(AFTER_LOGIN) },
    );
  };

  const fieldErr = mergeErrors(serverFieldErrors(login.error), errors);

  return (
    <form onSubmit={submit} noValidate className="grid gap-5">
      <AuthHeading title="Sign in">
        New to AppPilot?{" "}
        <Link href="/register" className={AUTH_LINK}>
          Create an account
        </Link>
      </AuthHeading>
      <FormError error={login.error && !Object.keys(serverFieldErrors(login.error)).length ? login.error : null} />
      <Field label="Email" htmlFor="email" error={fieldErr.email}>
        <IconInput icon={Mail} id="email" type="email" autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} aria-invalid={!!fieldErr.email} aria-describedby={fieldErr.email ? "email-error" : undefined} autoFocus />
      </Field>
      <Field label="Password" htmlFor="password" error={fieldErr.password}>
        <PasswordInput id="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} aria-invalid={!!fieldErr.password} aria-describedby={fieldErr.password ? "password-error" : undefined} />
      </Field>
      <div className="flex items-center justify-between gap-3">
        <label className="flex cursor-pointer items-center gap-2.5 text-[14px]">
          <Checkbox checked={remember} onCheckedChange={(v) => setRemember(v === true)} />
          Keep me signed in
        </label>
        <Link href="/forgot-password" className={AUTH_LINK}>
          Forgot password?
        </Link>
      </div>
      <Button type="submit" size="lg" loading={login.isPending} className={AUTH_BUTTON}>
        Sign in
      </Button>
    </form>
  );
}

export function RegisterForm() {
  const router = useRouter();
  const register = useRegister();
  const [form, setForm] = useState({ name: "", email: "", password: "" });
  const [accept, setAccept] = useState(false);
  const [errors, setErrors] = useState<Errors>({});

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const next: Errors = {
      name: !form.name.trim() ? "Enter your name." : undefined,
      email: !EMAIL_RE.test(form.email) ? "Enter a valid email address." : undefined,
      password: form.password.length < MIN_PASSWORD ? `Use at least ${MIN_PASSWORD} characters.` : undefined,
      terms: !accept ? "Accept the terms to continue." : undefined,
    };
    setErrors(next);
    if (Object.values(next).some(Boolean)) return;
    register.mutate(
      { ...form, name: form.name.trim(), acceptTerms: true },
      { onSuccess: () => router.replace(AFTER_LOGIN) },
    );
  };

  const fieldErr = mergeErrors(serverFieldErrors(register.error), errors);
  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement>) => setForm((f) => ({ ...f, [k]: e.target.value }));

  return (
    <form onSubmit={submit} noValidate className="grid gap-5">
      <AuthHeading title="Create your account">
        Already have one?{" "}
        <Link href="/login" className={AUTH_LINK}>
          Sign in
        </Link>
      </AuthHeading>
      <FormError error={register.error && !Object.keys(serverFieldErrors(register.error)).length ? register.error : null} />
      <Field label="Name" htmlFor="name" error={fieldErr.name}>
        <IconInput icon={UserRound} id="name" autoComplete="name" value={form.name} onChange={set("name")} aria-invalid={!!fieldErr.name} autoFocus />
      </Field>
      <Field label="Work email" htmlFor="email" error={fieldErr.email}>
        <IconInput icon={Mail} id="email" type="email" autoComplete="email" value={form.email} onChange={set("email")} aria-invalid={!!fieldErr.email} />
      </Field>
      <Field label="Password" htmlFor="password" error={fieldErr.password} hint={`At least ${MIN_PASSWORD} characters.`}>
        <PasswordInput id="password" autoComplete="new-password" value={form.password} onChange={set("password")} aria-invalid={!!fieldErr.password} />
      </Field>
      <div className="grid gap-1">
        <label className="flex cursor-pointer items-start gap-2.5 text-[14px] leading-snug">
          <Checkbox className="mt-0.5" checked={accept} onCheckedChange={(v) => setAccept(v === true)} aria-invalid={!!fieldErr.terms} />
          <span>I agree to the Terms of Service and Privacy Policy.</span>
        </label>
        {fieldErr.terms ? <p className="text-[13px] text-destructive" role="alert">{fieldErr.terms}</p> : null}
      </div>
      <Button type="submit" size="lg" loading={register.isPending} className={AUTH_BUTTON}>
        Create account
      </Button>
    </form>
  );
}

export function ForgotPasswordForm() {
  const forgot = useForgotPassword();
  const [email, setEmail] = useState("");
  const [error, setError] = useState<string>();

  if (forgot.isSuccess) {
    return (
      <div className="grid gap-4">
        <MailCheck className="size-6 text-success" aria-hidden />
        <h1 className="text-2xl font-semibold tracking-tight">Check your email</h1>
        <p className="text-[14px] text-muted-foreground">
          If an account exists for <span className="text-foreground">{email}</span>, we&apos;ve sent a link to reset
          your password. The link expires in 30 minutes.
        </p>
        <Button asChild variant="outline">
          <Link href="/login">Back to sign in</Link>
        </Button>
      </div>
    );
  }

  return (
    <form
      noValidate
      className="grid gap-4"
      onSubmit={(e) => {
        e.preventDefault();
        if (!EMAIL_RE.test(email)) return setError("Enter a valid email address.");
        setError(undefined);
        forgot.mutate({ email });
      }}
    >
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Reset your password</h1>
        <p className="mt-1 text-[14px] text-muted-foreground">
          Enter the email you signed up with and we&apos;ll send you a reset link.
        </p>
      </div>
      <FormError error={forgot.error} />
      <Field label="Email" htmlFor="email" error={error}>
        <Input id="email" type="email" autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} aria-invalid={!!error} autoFocus />
      </Field>
      <Button type="submit" size="lg" loading={forgot.isPending}>
        Send reset link
      </Button>
      <Link href="/login" className="text-center text-[14px] text-primary hover:underline">
        Back to sign in
      </Link>
    </form>
  );
}

export function ResetPasswordForm() {
  const params = useSearchParams();
  const token = params.get("token") ?? "";
  const reset = useResetPassword();
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [errors, setErrors] = useState<Errors>({});

  if (!token) {
    return (
      <div className="grid gap-4">
        <h1 className="text-2xl font-semibold tracking-tight">This link is incomplete</h1>
        <p className="text-[14px] text-muted-foreground">Open the link from your reset email again, or request a new one.</p>
        <Button asChild variant="outline"><Link href="/forgot-password">Request a new link</Link></Button>
      </div>
    );
  }

  if (reset.isSuccess) {
    return (
      <div className="grid gap-4">
        <h1 className="text-2xl font-semibold tracking-tight">Password updated</h1>
        <p className="text-[14px] text-muted-foreground">Sign in with your new password.</p>
        <Button asChild><Link href="/login">Sign in</Link></Button>
      </div>
    );
  }

  return (
    <form
      noValidate
      className="grid gap-4"
      onSubmit={(e) => {
        e.preventDefault();
        const next: Errors = {
          password: password.length < MIN_PASSWORD ? `Use at least ${MIN_PASSWORD} characters.` : undefined,
          confirm: confirm !== password ? "Passwords don't match." : undefined,
        };
        setErrors(next);
        if (next.password || next.confirm) return;
        reset.mutate({ token, password });
      }}
    >
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Choose a new password</h1>
      </div>
      <FormError error={reset.error} />
      <Field label="New password" htmlFor="password" error={errors.password} hint={`At least ${MIN_PASSWORD} characters.`}>
        <Input id="password" type="password" autoComplete="new-password" value={password} onChange={(e) => setPassword(e.target.value)} aria-invalid={!!errors.password} autoFocus />
      </Field>
      <Field label="Confirm new password" htmlFor="confirm" error={errors.confirm}>
        <Input id="confirm" type="password" autoComplete="new-password" value={confirm} onChange={(e) => setConfirm(e.target.value)} aria-invalid={!!errors.confirm} />
      </Field>
      <Button type="submit" size="lg" loading={reset.isPending}>
        Update password
      </Button>
    </form>
  );
}
