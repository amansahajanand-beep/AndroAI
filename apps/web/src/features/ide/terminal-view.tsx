"use client";

import { useEffect, useRef, useState } from "react";
import { useTheme } from "next-themes";
import type { TerminalClientFrame, TerminalServerFrame } from "@apppilot/contracts";
import { RotateCw } from "lucide-react";
import { PendingBackend } from "@/components/states/states";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api/client";
import { ApiError, errorMessage, isPendingBackend } from "@/lib/api/errors";

type State = { kind: "connecting" } | { kind: "open" } | { kind: "closed"; reason: string } | { kind: "error"; error: unknown };

/**
 * Only accepts the WebSocket URL issued by the terminal-session endpoint, and
 * only over wss (ws allowed for localhost during development). There is no
 * code path that opens a shell on the application server.
 */
function isAllowedSocketUrl(raw: string) {
  try {
    const u = new URL(raw, window.location.href);
    if (u.protocol === "wss:") return true;
    return u.protocol === "ws:" && (u.hostname === "localhost" || u.hostname === "127.0.0.1");
  } catch {
    return false;
  }
}

/** Reads a colour token where the terminal is mounted. */
function cssVar(name: string, el: Element = document.documentElement) {
  return getComputedStyle(el).getPropertyValue(name).trim() || undefined;
}

/** The terminal's colours, from the current theme's tokens. */
function terminalTheme(el: Element) {
  return {
    background: cssVar("--card", el),
    foreground: cssVar("--foreground", el),
    cursor: cssVar("--primary", el),
    selectionBackground: "#6b8cff55",
  };
}

export function TerminalView({ projectId }: { projectId: string }) {
  const host = useRef<HTMLDivElement>(null);
  const termRef = useRef<import("@xterm/xterm").Terminal | null>(null);
  const [state, setState] = useState<State>({ kind: "connecting" });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let disposed = false;
    let ws: WebSocket | null = null;
    let cleanupTerm: (() => void) | undefined;

    (async () => {
      setState({ kind: "connecting" });
      let session;
      try {
        session = await api.projects.createTerminal(projectId);
      } catch (e) {
        if (!disposed) setState({ kind: "error", error: e });
        return;
      }
      if (disposed) return;
      if (!isAllowedSocketUrl(session.wsUrl)) {
        setState({ kind: "error", error: new ApiError({ status: 0, code: "terminal.bad_url", message: "The terminal service returned an address the IDE won't connect to (only secure sandbox sockets are allowed)." }) });
        return;
      }

      const [{ Terminal }, { FitAddon }] = await Promise.all([import("@xterm/xterm"), import("@xterm/addon-fit")]);
      if (disposed || !host.current) return;
      const term = new Terminal({
        fontFamily: '"JetBrains Mono Variable", ui-monospace, monospace',
        fontSize: 12,
        cursorBlink: true,
        convertEol: true,
        theme: terminalTheme(host.current),
      });
      termRef.current = term;
      const fit = new FitAddon();
      term.loadAddon(fit);
      term.open(host.current);
      fit.fit();

      ws = new WebSocket(session.wsUrl);
      const sendFrame = (f: TerminalClientFrame) => ws?.readyState === WebSocket.OPEN && ws.send(JSON.stringify(f));
      ws.onopen = () => {
        setState({ kind: "open" });
        sendFrame({ type: "resize", cols: term.cols, rows: term.rows });
        term.focus();
      };
      ws.onmessage = (ev) => {
        try {
          const frame = JSON.parse(String(ev.data)) as TerminalServerFrame;
          if (frame.type === "output") term.write(frame.data);
          else if (frame.type === "exit") {
            term.write(`\r\n\x1b[2m[process exited with code ${frame.code}]\x1b[0m\r\n`);
            setState({ kind: "closed", reason: `Process exited with code ${frame.code}.` });
          }
        } catch {
          /* ignore malformed frames */
        }
      };
      ws.onclose = () => !disposed && setState((s) => (s.kind === "closed" ? s : { kind: "closed", reason: "Disconnected from the sandbox." }));
      ws.onerror = () => !disposed && setState({ kind: "closed", reason: "Couldn't connect to the sandbox terminal." });

      const input = term.onData((data) => sendFrame({ type: "input", data }));
      const ro = new ResizeObserver(() => {
        try {
          fit.fit();
          sendFrame({ type: "resize", cols: term.cols, rows: term.rows });
        } catch {
          /* container hidden */
        }
      });
      ro.observe(host.current);
      cleanupTerm = () => {
        ro.disconnect();
        input.dispose();
        termRef.current = null;
        term.dispose();
      };
    })();

    return () => {
      disposed = true;
      ws?.close();
      cleanupTerm?.();
    };
  }, [projectId, attempt]);

  // Re-colour the open terminal when the app switches between light and dark.
  const { resolvedTheme } = useTheme();
  useEffect(() => {
    const id = requestAnimationFrame(() => {
      if (termRef.current && host.current) termRef.current.options.theme = terminalTheme(host.current);
    });
    return () => cancelAnimationFrame(id);
  }, [resolvedTheme]);

  if (state.kind === "error") {
    return isPendingBackend(state.error) ? (
      <PendingBackend endpoint="projects.terminal.create" compact>
        The terminal runs in an isolated per-project sandbox. {state.error instanceof Error ? state.error.message : null}
      </PendingBackend>
    ) : (
      <div className="grid h-full place-items-center p-4 text-center text-[14px]">
        <div>
          <p>{errorMessage(state.error)}</p>
          <Button variant="outline" size="sm" className="mt-2" onClick={() => setAttempt((a) => a + 1)}>
            <RotateCw /> Try again
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className="relative h-full">
      <div ref={host} className="h-full" aria-label="Sandbox terminal" />
      {state.kind === "connecting" ? <p className="absolute left-3 top-2 text-[13px] text-muted-foreground">Starting sandbox terminal…</p> : null}
      {state.kind === "closed" ? (
        <div className="absolute right-3 top-2 flex items-center gap-2 rounded-sm border border-border bg-popover px-2 py-1 text-[13px]">
          {state.reason}
          <Button variant="link" size="sm" className="h-auto text-[13px]" onClick={() => setAttempt((a) => a + 1)}>
            Reconnect
          </Button>
        </div>
      ) : null}
    </div>
  );
}
