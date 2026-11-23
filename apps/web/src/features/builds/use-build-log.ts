"use client";

import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import type { Build, BuildLogLine } from "@apppilot/contracts";
import { qk, useBuildLogs } from "@/lib/api/hooks";
import { useEventStream } from "@/lib/realtime/use-event-stream";

/** Full log for finished builds; full log + streamed lines for running ones. */
export function useBuildLog(build: Build | undefined | null) {
  const qc = useQueryClient();
  const logs = useBuildLogs(build?.id ?? null);
  const running = build?.status === "running" || build?.status === "queued";
  const [streamed, setStreamed] = useState<{ buildId: string; lines: BuildLogLine[] }>({ buildId: "", lines: [] });

  useEventStream({
    endpoint: "builds.logs.stream",
    params: build ? { buildId: build.id } : {},
    events: ["log", "end"],
    enabled: !!build && running && logs.isSuccess,
    onEvent: (type, data) => {
      if (!build) return;
      if (type === "end") {
        qc.invalidateQueries({ queryKey: ["builds"] });
        qc.invalidateQueries({ queryKey: qk.build(build.id) });
        return;
      }
      const line = data as BuildLogLine;
      setStreamed((s) => ({
        buildId: build.id,
        lines: s.buildId === build.id ? [...s.lines, line] : [line],
      }));
    },
  });

  const base = logs.data ? logs.data.split("\n") : [];
  const extra = streamed.buildId === build?.id ? streamed.lines.filter((l) => l.seq > base.length).map((l) => l.line) : [];
  return { lines: [...base, ...extra], query: logs, live: running };
}
