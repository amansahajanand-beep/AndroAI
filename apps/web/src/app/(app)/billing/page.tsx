import type { Metadata } from "next";
import { BillingScreen } from "@/features/billing/billing-screen";

export const metadata: Metadata = { title: "Billing and usage" };
export default function Page() {
  return <BillingScreen />;
}
