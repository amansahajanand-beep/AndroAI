"use client";

import { useEffect, useRef, useState } from "react";
import type { EndpointKey } from "@apppilot/contracts";
import { IS_MOCK } from "@/lib/env";
import { resolvePath } from "@/lib/api/transport";

export type StreamStatus = "idle" | "connecting" | "open" | "reconnecting" | "closed";

type Handler = (type: string, data: unknown) => void;

/**
 * Subscribes to a server-sent-events endpoint from the contracts registry.
 * The backend sends named events (`event: task.updated`) with JSON data.
 * EventSource reconnects automatically; we surface the state for the UI.
 */
export function useEventStream({
  endpoint,
  params,
  events,
  onEvent,
  enabled = true,
}: {
  endpoint: EndpointKey;
  params: Record<string, string>;
  events: readonly string[];
  onEvent: Handler;
  enabled?: boolean;
}): StreamStatus {
  // Status is keyed by stream path so a new subscription starts as "connecting"
  // without a synchronous setState inside the effect.
  const [state, setState] = useState<{ path: string | null; status: StreamStatus }>({ path: null, status: "idle" });
  const handlerRef = useRef(onEvent);
  useEffect(() => {
    handlerRef.current = onEvent;
  });

  const path = enabled ? safeResolve(endpoint, params) : null;
  const eventsKey = events.join(",");

  useEffect(() => {
    if (!path) return;
    const types = eventsKey.split(",");
    let cleanup: (() => void) | undefined;
    let cancelled = false;
    const setStatus = (status: StreamStatus) => !cancelled && setState({ path, status });

    if (IS_MOCK) {
      import("@/lib/api/mock/bus").then(({ mockBus }) => {
        if (cancelled) return;
        setStatus("open");
        cleanup = mockBus.subscribe(path, (type, data) => {
          if (types.includes(type)) handlerRef.current(type, data);
        });
      });
    } else {
      const es = new EventSource(path, { withCredentials: true });
      es.onopen = () => setStatus("open");
      es.onerror = () =>
        setStatus(es.readyState === EventSource.CLOSED ? "closed" : "reconnecting");
      const listeners = types.map((type) => {
        const fn = (e: MessageEvent<string>) => {
          try {
            handlerRef.current(type, JSON.parse(e.data));
          } catch {
            handlerRef.current(type, e.data);
          }
        };
        es.addEventListener(type, fn);
        return [type, fn] as const;
      });
      cleanup = () => {
        listeners.forEach(([t, fn]) => es.removeEventListener(t, fn));
        es.close();
      };
    }

    return () => {
      cancelled = true;
      cleanup?.();
    };
  }, [path, eventsKey]);

  if (!path) return "idle";
  return state.path === path ? state.status : "connecting";
}

function safeResolve(endpoint: EndpointKey, params: Record<string, string>) {
  try {
    return resolvePath(endpoint, params);
  } catch {
    return null;
  }
}
