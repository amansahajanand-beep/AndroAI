import type { Metadata, Viewport } from "next";
import "./globals.css";
import { Providers } from "./providers";

export const metadata: Metadata = {
  title: { default: "AppPilot AI", template: "%s · AppPilot AI" },
  description:
    "Build, modify and test Android apps in the browser with AI agents that plan, write, build and repair code.",
};

export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: dark)", color: "#07060f" },
    { media: "(prefers-color-scheme: light)", color: "#f7f6fd" },
  ],
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
