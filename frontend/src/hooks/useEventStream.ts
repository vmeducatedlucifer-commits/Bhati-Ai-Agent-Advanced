import { useEffect, useRef } from "react";
import { streamUrl } from "@/lib/api";
import { useStore } from "@/lib/store";
import type { AgentEvent } from "@/types/events";

/**
 * Keeps one SSE connection open per thread. On reconnect it resumes from the last
 * sequence number the store saw, so a dropped connection never loses events.
 */
export function useEventStream(threadId: string | null) {
  const applyEvent = useStore((s) => s.applyEvent);
  const sourceRef = useRef<EventSource | null>(null);
  const retryRef = useRef<number | null>(null);
  const attemptsRef = useRef(0);

  useEffect(() => {
    if (!threadId) return;

    let cancelled = false;

    const connect = () => {
      if (cancelled) return;
      const after = useStore.getState().lastSeq;
      const source = new EventSource(streamUrl(threadId, after));
      sourceRef.current = source;

      const handle = (event: MessageEvent) => {
        try {
          applyEvent(JSON.parse(event.data) as AgentEvent);
        } catch {
          /* keep-alive comment or malformed frame */
        }
      };

      source.onopen = () => {
        attemptsRef.current = 0;
      };
      source.onmessage = handle;
      // The server names every event, so listen on the named channels too.
      for (const name of [
        "run_start", "run_end", "message_start", "text_delta", "reasoning_delta",
        "message_end", "tool_call", "tool_progress", "tool_result", "terminal_start",
        "terminal_output", "terminal_end", "todos", "thinking", "skill", "artifact", "memory",
        "preview", "preview_stopped", "browser_navigate", "browser_action", "browser_recovery", "subagent_start", "subagent_step",
        "subagent_end", "subagent_event", "permission_request", "usage", "compacted",
        "title", "error", "interrupted",
      ]) {
        source.addEventListener(name, handle as EventListener);
      }

      source.onerror = (event: Event) => {
        const target = event.target as EventSource;
        // If auth failed (401/403), don't retry - the user needs to log in again
        if (target.readyState === EventSource.CLOSED) {
          source.close();
          sourceRef.current = null;
          if (cancelled) return;
          attemptsRef.current += 1;
          const delay = Math.min(15_000, 500 * 2 ** Math.min(attemptsRef.current, 5));
          retryRef.current = window.setTimeout(connect, delay);
        }
      };
    };

    connect();

    return () => {
      cancelled = true;
      if (retryRef.current) window.clearTimeout(retryRef.current);
      sourceRef.current?.close();
      sourceRef.current = null;
    };
  }, [threadId, applyEvent]);
}
