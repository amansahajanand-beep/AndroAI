"use client";

import { useQueryClient } from "@tanstack/react-query";
import type { AgentStreamEvent, AgentTask, AgentTimelineEvent, ChatMessage } from "@apppilot/contracts";
import { TERMINAL_AGENT_STATUSES } from "@apppilot/contracts";
import { qk } from "@/lib/api/hooks";
import { useEventStream } from "@/lib/realtime/use-event-stream";

const EVENTS = ["task.updated", "timeline.appended", "message.completed", "message.delta", "changeset.ready"] as const;

/**
 * Keeps a task, its timeline and the project's chat in the React Query cache
 * up to date from the agent SSE stream.
 */
export function useTaskStream(task: AgentTask | undefined) {
  const qc = useQueryClient();
  const active = !!task && !TERMINAL_AGENT_STATUSES.includes(task.status);
  return useEventStream({
    endpoint: "agent.tasks.events",
    params: task ? { taskId: task.id } : {},
    events: EVENTS,
    enabled: active,
    onEvent: (_type, raw) => {
      const ev = raw as AgentStreamEvent;
      switch (ev.type) {
        case "task.updated":
          qc.setQueryData(qk.task(ev.task.id), ev.task);
          qc.invalidateQueries({ queryKey: ["agent", "tasks"] });
          if (TERMINAL_AGENT_STATUSES.includes(ev.task.status)) {
            qc.invalidateQueries({ queryKey: qk.projects });
          }
          break;
        case "timeline.appended":
          qc.setQueryData<AgentTimelineEvent[]>(qk.timeline(ev.event.taskId), (old) =>
            old?.some((e) => e.id === ev.event.id) ? old : [...(old ?? []), ev.event],
          );
          break;
        case "message.delta":
          if (task)
            qc.setQueryData<ChatMessage[]>(qk.messages(task.projectId), (old) =>
              old?.map((m) => (m.id === ev.messageId ? { ...m, content: ev.content } : m)),
            );
          break;
        case "message.completed":
        case "changeset.ready":
          if (task) qc.invalidateQueries({ queryKey: qk.messages(task.projectId) });
          if (ev.type === "changeset.ready") qc.setQueryData(qk.changeSet(ev.changeSet.id), ev.changeSet);
          break;
      }
    },
  });
}
