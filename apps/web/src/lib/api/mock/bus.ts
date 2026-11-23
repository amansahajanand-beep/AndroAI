/**
 * DEV-ONLY in-memory event bus that stands in for SSE streams in mock mode.
 * Channels are the resolved endpoint paths, e.g. /api/v1/agent/tasks/t_1/events.
 */
type Listener = (type: string, data: unknown) => void;

const channels = new Map<string, Set<Listener>>();

export const mockBus = {
  subscribe(channel: string, fn: Listener) {
    let set = channels.get(channel);
    if (!set) {
      set = new Set();
      channels.set(channel, set);
    }
    set.add(fn);
    return () => {
      set?.delete(fn);
    };
  },
  emit(channel: string, type: string, data: unknown) {
    channels.get(channel)?.forEach((fn) => fn(type, data));
  },
};
