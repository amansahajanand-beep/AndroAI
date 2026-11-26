import { AuthShell } from "@/features/auth/auth-shell";

/** Shell for Sign in and Register (shared with Forgot/Reset password, so every auth screen matches). */
export default function AccessLayout({ children }: { children: React.ReactNode }) {
  return <AuthShell>{children}</AuthShell>;
}
