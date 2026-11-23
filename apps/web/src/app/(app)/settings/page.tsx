import type { Metadata } from "next";
import { ProfileSettingsScreen } from "@/features/profile/profile-settings";

export const metadata: Metadata = { title: "Settings" };
export default function Page() {
  return <ProfileSettingsScreen />;
}
