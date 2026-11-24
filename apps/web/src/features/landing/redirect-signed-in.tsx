"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useSession } from "@/lib/api/hooks";

/** Signed-in visitors skip the marketing page and land on the dashboard. */
export function RedirectSignedIn() {
  const router = useRouter();
  const session = useSession();
  useEffect(() => {
    if (session.data) router.replace("/dashboard");
  }, [session.data, router]);
  return null;
}
