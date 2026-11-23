import Link from "next/link";
import { Logo } from "@/components/brand/logo";
import { MockModeBadge } from "@/components/layout/chrome";

export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="app-ambient flex min-h-dvh flex-col">
      <header className="flex h-14 items-center justify-between px-5">
        <Link href="/" aria-label="AppPilot home">
          <Logo />
        </Link>
        <MockModeBadge />
      </header>
      <main className="flex flex-1 items-start justify-center px-5 pb-16 pt-[8vh]">
        <div className="w-full max-w-sm animate-fade-up">{children}</div>
      </main>
    </div>
  );
}
