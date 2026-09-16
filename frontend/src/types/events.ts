/** Agent event names. Mirror of `backend/app/agent/events.py`. */
export type AgentEventType =
  | "run_start"
  | "run_end"
  | "message_start"
  | "text_delta"
  | "reasoning_delta"
  | "message_end"
  | "tool_call"
  | "tool_progress"
  | "thinking_progress"
  | "tool_result"
  | "terminal_start"
  | "terminal_output"
  | "terminal_end"
  | "todos"
  | "plan_mode_entered"
  | "plan_mode_exited"
  | "thinking"
  | "skill"
  | "artifact"
  | "memory"
  | "preview"
  | "preview_stopped"
  | "browser_navigate"
  | "browser_action"
  | "browser_recovery"
  | "subagent_start"
  | "subagent_step"
  | "subagent_end"
  | "subagent_event"
  | "subagent_spawned"
  | "subagent_status"
  | "swarm_deployed"
  | "swarm_status"
  | "permission_request"
  | "usage"
  | "compacted"
  | "title"
  | "error"
  | "interrupted";

export interface AgentEvent {
  type: AgentEventType;
  thread_id: string;
  seq: number;
  [key: string]: unknown;
}
