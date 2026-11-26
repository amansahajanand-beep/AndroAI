import type { Metadata } from "next";
import { Suspense } from "react";
import { ProfileSettingsScreen } from "@/features/profile/profile-settings";

export const metadata: Metadata = { title: "Settings" };
export default function Page() {
  return (
    <Suspense>
      <ProfileSettingsScreen />
    </Suspense>
  );
}
