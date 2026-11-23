import { AuthGuard } from "@/components/layout/auth-guard";

export default function IdeGroupLayout({ children }: { children: React.ReactNode }) {
  return <AuthGuard>{children}</AuthGuard>;
}
