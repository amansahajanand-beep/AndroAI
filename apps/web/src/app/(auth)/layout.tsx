import { AuthShell } from "@/features/auth/auth-shell";

/** Shell for Forgot and Reset password: the same one as Sign in and Register. */
export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return <AuthShell>{children}</AuthShell>;
}
