import { ApiStatus } from "@/components/api-status";

export default function Home() {
  return (
    <main className="mx-auto flex w-full max-w-2xl flex-1 flex-col justify-center gap-6 px-6 py-24">
      <h1 className="text-4xl font-semibold tracking-tight">AndroAI</h1>
      <p className="text-muted-foreground">
        AI-powered Android app development. Repository foundation — product
        screens are owned by the frontend developer and not built yet.
      </p>
      <ApiStatus />
    </main>
  );
}
