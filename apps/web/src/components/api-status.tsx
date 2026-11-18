"use client";

import { useEffect, useState } from "react";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

type State = { kind: "loading" } | { kind: "ok"; version: string } | { kind: "down" };

export function ApiStatus() {
  const [state, setState] = useState<State>({ kind: "loading" });

  useEffect(() => {
    const controller = new AbortController();
    fetch(`${API_URL}/health`, { signal: controller.signal })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((body) => setState({ kind: "ok", version: body.version }))
      .catch((e) => {
        if (e.name !== "AbortError") setState({ kind: "down" });
      });
    return () => controller.abort();
  }, []);

  const text =
    state.kind === "loading"
      ? "Checking API…"
      : state.kind === "ok"
        ? `API online (v${state.version})`
        : "API unreachable";

  return (
    <p role="status" className="rounded-md border px-3 py-2 text-sm">
      {text}
    </p>
  );
}
