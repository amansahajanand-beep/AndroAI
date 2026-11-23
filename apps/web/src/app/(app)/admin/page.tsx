import type { Metadata } from "next";
import { AuthGuard } from "@/components/layout/auth-guard";
import { AdminScreen } from "@/features/admin/admin-screen";

export const metadata: Metadata = { title: "Admin" };
export default function Page() {
  return (
    <AuthGuard requireAdmin>
      <AdminScreen />
    </AuthGuard>
  );
}
