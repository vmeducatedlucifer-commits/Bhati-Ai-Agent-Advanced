import { create } from "zustand";
import { api } from "@/lib/api";
import type {
  Artifact,
  Capabilities,
  ChatMessage,
  ModelOption,
  PermissionRequest,
  Project,
  SandboxInfo,
  SubAgentListItem,
  SwarmListItem,
  Thread,
  Todo,
  ToolCall,
} from "@/types";
import type { AgentEvent } from "@/types/events";
import { ApiError } from "@/lib/api";

export type ComputerTab = "activity" | "plan" | "terminal" | "editor" | "browser" | "files" | "artifacts" | "agents";

export interface ActivityItem {
  id: string;
  kind: "tool" | "thinking" | "skill" | "subagent" | "error" | "compaction" | "note";
  title: string;
  detail?: string;
  status?: string;
  at: number;
}

interface State {
  // bootstrap
  ready: boolean;
  capabilities: Capabilities | null;

  // data
  projects: Project[];
  threads: Thread[];
  models: ModelOption[];
  activeProjectId: string | null;
  activeThreadId: string | null;

  // conversation
  messages: ChatMessage[];
  todos: Todo[];
  artifacts: Artifact[];
  activity: ActivityItem[];
  permission: PermissionRequest | null;
  planContent: string | null;
  running: boolean;
  activeProgress: { kind: "tool" | "thinking"; name?: string; elapsed_s: number; status: string; id?: string } | null;
  lastSeq: number;
  usage: { prompt_tokens: number; completion_tokens: number };
  runMeta: { model?: string; provider?: string; sandbox?: string; tools?: number } | null;

  // agent computer
  computerTab: ComputerTab;
  computerOpen: boolean;
  terminalLines: string[];
  openFile: { path: string; content: string; dirty: boolean } | null;
  activeDiff: { path: string; diff: string } | null;
  browserUrl: string | null;
  sandbox: SandboxInfo | null;
  followAgent: boolean;
  voiceEnabled: boolean;
  voiceMode: "type" | "send" | "confirm";
  voiceTrigger: string;
  voiceRate: number;
  voicePitch: number;
  wakeEnabled: boolean;
  setWakeEnabled: (value: boolean) => void;
  /** Auto-translate: wrap outgoing prompts so the agent replies in the target language. */
  translateMode: boolean;
  translateTarget: "en" | "hi";
  callActive: boolean;
  setCallActive: (value: boolean) => void;
  /** Low-end performance mode: hides ambient effects, keeps functional motion. */
  lowPerf: boolean;

  // device & network adaptive modes
  deviceMode: "auto" | "mobile" | "desktop";
  effectiveDeviceMode: "mobile" | "desktop";
  networkMode: "auto" | "ultra_low" | "high_speed";
  effectiveNetworkMode: "ultra_low" | "high_speed";
  networkStats: {
    effectiveType: string;
    downlink: number;
    rtt: number;
    effectiveSpeedKbps: number;
    isOnline: boolean;
  };
  setDeviceMode: (mode: "auto" | "mobile" | "desktop") => void;
  setEffectiveDeviceMode: (mode: "mobile" | "desktop") => void;
  setNetworkMode: (mode: "auto" | "ultra_low" | "high_speed") => void;
  setEffectiveNetworkMode: (mode: "ultra_low" | "high_speed") => void;
  updateNetworkStats: (stats: Partial<{
    effectiveType: string;
    downlink: number;
    rtt: number;
    effectiveSpeedKbps: number;
    isOnline: boolean;
  }>) => void;

  // actions
  bootstrap: () => Promise<void>;
  selectProject: (id: string | null) => Promise<void>;
  selectThread: (id: string | null) => Promise<void>;
  createProject: (name: string, description?: string) => Promise<Project>;
  createThread: (projectId: string) => Promise<Thread>;
  deleteThread: (id: string) => Promise<void>;
  deleteProject: (id: string) => Promise<void>;
  refreshProjects: () => Promise<void>;
  refreshThreads: () => Promise<void>;
  refreshModels: () => Promise<void>;
  setThreadModel: (providerId: string, model: string) => Promise<void>;
  setThreadMode: (mode: Thread["mode"]) => Promise<void>;
  setPermissionMode: (mode: Thread["permission_mode"]) => Promise<void>;

  send: (content: string) => Promise<void>;
  interrupt: () => Promise<void>;
  answerPermission: (decision: "allow" | "deny" | "allow_always") => Promise<void>;
  applyEvent: (event: AgentEvent) => void;

  setComputerTab: (tab: ComputerTab) => void;
  toggleComputer: () => void;
  setFollowAgent: (value: boolean) => void;
  setLowPerf: (value: boolean) => void;
  setVoiceSettings: (settings: Partial<{voiceEnabled: boolean; voiceMode: "type"|"send"|"confirm"; voiceTrigger: string; voiceRate: number; voicePitch: number; translateMode: boolean; translateTarget: "en"|"hi"}>) => void;
  openPath: (path: string) => Promise<void>;
  saveOpenFile: () => Promise<void>;
  setOpenFileContent: (content: string) => void;
  refreshSandbox: () => Promise<void>;
  refreshArtifacts: () => Promise<void>;
  clearTerminal: () => void;
  navigateBrowser: (url: string) => void;
  closeBrowser: () => void;

  // ---- pro features ----
  draft: string | null;
  setDraft: (draft: string | null) => void;
  consumeDraft: () => string | null;
  outbox: { id: string; threadId: string; content: string; at: number }[];
  flushOutbox: () => Promise<void>;
  pinnedIds: string[];
  togglePin: (messageId: string) => void;
  editResend: (messageId: string, newContent: string) => Promise<void>;
  regenerate: (messageId: string) => Promise<void>;
  forkFrom: (messageId?: string) => Promise<Thread | null>;
  notifyEnabled: boolean;
  setNotifyEnabled: (value: boolean) => void;
  accentHue: number | null;
  setAccentHue: (hue: number | null) => void;
  keymap: { newChat: string; sidebar: string; settings: string };
  setKeymap: (map: Partial<State["keymap"]>) => void;
  lockHash: string | null;
  unlocked: boolean;
  setPin: (pin: string | null) => Promise<void>;
  unlock: (pin: string) => Promise<boolean>;
  lockNow: () => void;
  installEvt: unknown;
  setInstallEvt: (evt: unknown) => void;
  promptInstall: () => Promise<void>;

  // ---- agent management ----
  subAgents: SubAgentListItem[];
  swarms: SwarmListItem[];
  selectedAgentId: string | null;
  selectedSwarmId: string | null;
  refreshSubAgents: () => Promise<void>;
  refreshSwarms: () => Promise<void>;
  selectAgent: (agentId: string | null) => void;
  selectSwarm: (swarmId: string | null) => void;
  spawnAgent: (data: { agent_type: string; name: string; prompt: string; priority?: string; max_steps?: number }) => Promise<void>;
  killAgent: (agentId: string, force?: boolean) => Promise<void>;
  killAllAgents: () => Promise<void>;
  deploySwarmAction: (data: { name: string; prompt: string; strategy?: string; agent_count?: number; agent_type?: string; priority?: string; max_steps?: number }) => Promise<void>;
  killSwarmAction: (swarmId: string) => Promise<void>;
}

const emptyUsage = { prompt_tokens: 0, completion_tokens: 0 };

const OUTBOX_KEY = "bhati.outbox";
const KEYMAP_KEY = "bhati.keymap";
const DEFAULT_KEYMAP = { newChat: "n", sidebar: "b", settings: "," };

function loadOutbox(): State["outbox"] {
  try {
    const raw = localStorage.getItem(OUTBOX_KEY);
    const parsed = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function saveOutbox(items: State["outbox"]) {
  try {
    localStorage.setItem(OUTBOX_KEY, JSON.stringify(items));
  } catch {
    /* storage unavailable */
  }
}

function loadKeymap(): State["keymap"] {
  try {
    const raw = localStorage.getItem(KEYMAP_KEY);
    if (raw) return { ...DEFAULT_KEYMAP, ...JSON.parse(raw) };
  } catch {
    /* ignore */
  }
  return { ...DEFAULT_KEYMAP };
}

async function sha256(text: string): Promise<string> {
  const bytes = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(`bhati-pin:${text}`));
  return [...new Uint8Array(bytes)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

function applyAccentHue(hue: number | null) {
  const root = document.documentElement;
  if (hue === null || Number.isNaN(hue)) {
    root.style.removeProperty("--primary");
    root.style.removeProperty("--ring");
  } else {
    root.style.setProperty("--primary", `${hue} 63% 59%`);
    root.style.setProperty("--ring", `${hue} 63% 59%`);
  }
}

function upsertMessage(messages: ChatMessage[], id: string, patch: Partial<ChatMessage>): ChatMessage[] {
  const index = messages.findIndex((m) => m.id === id);
  if (index === -1) {
    return [
      ...messages,
      {
        id,
        role: "assistant",
        content: "",
        tool_calls: [],
        ...patch,
      } as ChatMessage,
    ];
  }
  const next = [...messages];
  next[index] = { ...next[index], ...patch };
  return next;
}

function patchToolCall(
  messages: ChatMessage[],
  toolCallId: string,
  patch: Partial<ToolCall>,
): ChatMessage[] {
  for (let i = messages.length - 1; i >= 0; i -= 1) {
    const index = messages[i].tool_calls.findIndex((t) => t.id === toolCallId);
    if (index !== -1) {
      const next = [...messages];
      const calls = [...next[i].tool_calls];
      calls[index] = { ...calls[index], ...patch };
      next[i] = { ...next[i], tool_calls: calls };
      return next;
    }
  }
  return messages;
}

/**
 * Settle open streams when a run dies without message_end (interrupt, error,
 * disconnect). Otherwise thinking indicators spin forever on dead messages.
 */
function settleStreaming(messages: ChatMessage[]): ChatMessage[] {
  return messages.map((m) =>
    m.streaming
      ? {
          ...m,
          streaming: false,
          tool_calls: m.tool_calls.map((t) =>
            t.status === "running" ? { ...t, status: "error" as const } : t,
          ),
        }
      : m,
  );
}

export const useStore = create<State>((set, get) => ({
  ready: false,
  capabilities: null,
  projects: [],
  threads: [],
  models: [],
  activeProjectId: null,
  activeThreadId: null,
  messages: [],
  todos: [],
  artifacts: [],
  activity: [],
  permission: null,
  planContent: null,
  running: false,
  activeProgress: null,
  lastSeq: 0,
  usage: { ...emptyUsage },
  runMeta: null,
  computerTab: "activity",
  computerOpen: true,
  terminalLines: [],
  openFile: null,
  activeDiff: null,
  browserUrl: null,
  sandbox: null,
  followAgent: true,
  voiceEnabled: localStorage.getItem('bhati.voice') === 'true',
  voiceMode: (localStorage.getItem('bhati.voiceMode') as any) || 'send',
  voiceTrigger: localStorage.getItem('bhati.voiceTrigger') || 'send now',
  voiceRate: Number(localStorage.getItem('bhati.voiceRate')) || 1,
  voicePitch: Number(localStorage.getItem('bhati.voicePitch')) || 1,
  wakeEnabled: localStorage.getItem('bhati.wake') === '1',
  translateMode: localStorage.getItem('bhati.translateMode') === '1',
  translateTarget: (localStorage.getItem('bhati.translateTarget') as "en" | "hi") || "en",
  callActive: false,
  lowPerf: localStorage.getItem('bhati.lowperf') === '1',
  deviceMode: ((localStorage.getItem('bhati.deviceMode') as any) || 'auto') as "auto" | "mobile" | "desktop",
  effectiveDeviceMode: (() => {
    const saved = typeof window !== "undefined" ? localStorage.getItem("bhati.deviceMode") : null;
    if (saved === "mobile" || saved === "desktop") return saved;
    return typeof window !== "undefined" && window.innerWidth < 768 ? "mobile" : "desktop";
  })(),
  networkMode: ((localStorage.getItem('bhati.networkMode') as any) || 'auto') as "auto" | "ultra_low" | "high_speed",
  effectiveNetworkMode: localStorage.getItem("bhati.networkMode") === "ultra_low" ? "ultra_low" : "high_speed",
  networkStats: {
    effectiveType: "4g",
    downlink: 10,
    rtt: 50,
    effectiveSpeedKbps: 10000,
    isOnline: typeof navigator !== "undefined" ? navigator.onLine : true,
  },
  draft: null,
  outbox: loadOutbox(),
  pinnedIds: [],
  notifyEnabled: localStorage.getItem('bhati.notify') === '1',
  accentHue: (() => {
    const raw = localStorage.getItem('bhati.accentHue');
    const n = raw === null ? null : Number(raw);
    return n === null || Number.isNaN(n) ? null : n;
  })(),
  keymap: loadKeymap(),
  lockHash: localStorage.getItem('bhati.pinHash'),
  unlocked: sessionStorage.getItem('bhati.unlocked') === '1',
  installEvt: null,

  // ---- agent management ----
  subAgents: [],
  swarms: [],
  selectedAgentId: null,
  selectedSwarmId: null,

  // ---- bootstrap -------------------------------------------------------

  async bootstrap() {
    if (get().lowPerf) document.documentElement.classList.add("perf-low");
    applyAccentHue(get().accentHue);
    const [capabilities, projects, models] = await Promise.all([
      api.capabilities().catch(() => null),
      api.listProjects().catch(() => []),
      api.listModels().catch(() => []),
    ]);
    set({ capabilities, projects, models, ready: true });

    const lastProject = localStorage.getItem("bhati.project");
    const target = projects.find((p) => p.id === lastProject) ?? projects[0];
    if (target) await get().selectProject(target.id);
    void get().flushOutbox();
  },

  async selectProject(id) {
    set({ activeProjectId: id, activeThreadId: null, messages: [], todos: [], activity: [] });
    if (!id) {
      set({ threads: [] });
      return;
    }
    localStorage.setItem("bhati.project", id);
    const threads = await api.listThreads(id);
    set({ threads });
    const lastThread = localStorage.getItem(`bhati.thread.${id}`);
    const target = threads.find((t) => t.id === lastThread) ?? threads[0];
    if (target) await get().selectThread(target.id);
  },

  async selectThread(id) {
    set({
      activeThreadId: id,
      messages: [],
      todos: [],
      activity: [],
      artifacts: [],
      terminalLines: [],
      openFile: null,
      activeDiff: null,
      browserUrl: null,
      permission: null,
      planContent: null,
      lastSeq: 0,
      usage: { ...emptyUsage },
      runMeta: null,
      pinnedIds: [],
    });
    if (!id) return;
    const projectId = get().activeProjectId;
    if (projectId) localStorage.setItem(`bhati.thread.${projectId}`, id);
    try {
      const raw = localStorage.getItem(`bhati.pins.${id}`);
      if (raw) set({ pinnedIds: JSON.parse(raw) });
    } catch {
      /* ignore */
    }

    const [thread, messages, status, artifacts] = await Promise.all([
      api.getThread(id),
      api.listMessages(id),
      api.runStatus(id).catch(() => ({ running: false, pending_permissions: [] })),
      api.listArtifacts(id).catch(() => []),
    ]);
    set({
      messages,
      todos: thread.todos ?? [],
      running: status.running,
      artifacts,
      permission: (status.pending_permissions?.[0] as PermissionRequest) ?? null,
      threads: get().threads.map((t) => (t.id === id ? thread : t)),
    });
    void get().refreshSandbox();
  },

  async createProject(name, description = "") {
    const project = await api.createProject({ name, description });
    set({ projects: [project, ...get().projects] });
    await get().selectProject(project.id);
    return project;
  },

  async createThread(projectId) {
    const current = get();
    const model = current.threads[0]?.model ?? current.models[0]?.model ?? "";
    const providerId = current.threads[0]?.provider_id ?? current.models[0]?.provider_id ?? null;
    const thread = await api.createThread({ project_id: projectId, model, provider_id: providerId });
    set({ threads: [thread, ...current.threads] });
    await get().selectThread(thread.id);
    return thread;
  },

  async deleteThread(id) {
    await api.deleteThread(id);
    const threads = get().threads.filter((t) => t.id !== id);
    set({ threads });
    if (get().activeThreadId === id) await get().selectThread(threads[0]?.id ?? null);
  },

  async deleteProject(id) {
    await api.deleteProject(id);
    const projects = get().projects.filter((p) => p.id !== id);
    set({ projects });
    if (get().activeProjectId === id) {
      localStorage.removeItem("bhati.project");
      await get().selectProject(projects[0]?.id ?? null);
    }
  },

  async refreshThreads() {
    const projectId = get().activeProjectId;
    if (!projectId) return;
    set({ threads: await api.listThreads(projectId) });
  },

  async refreshProjects() {
    set({ projects: await api.listProjects().catch(() => []) });
  },

  async refreshModels() {
    set({ models: await api.listModels().catch(() => []) });
  },

  async setThreadModel(providerId, model) {
    const id = get().activeThreadId;
    if (!id) return;
    const thread = await api.updateThread(id, { provider_id: providerId, model });
    set({ threads: get().threads.map((t) => (t.id === id ? thread : t)) });
  },

  async setThreadMode(mode) {
    const id = get().activeThreadId;
    if (!id) return;
    const thread = await api.updateThread(id, { mode });
    set({ threads: get().threads.map((t) => (t.id === id ? thread : t)) });
  },

  async setPermissionMode(permission_mode) {
    const id = get().activeThreadId;
    if (!id) return;
    const thread = await api.updateThread(id, { permission_mode });
    set({ threads: get().threads.map((t) => (t.id === id ? thread : t)) });
  },

  // ---- conversation ----------------------------------------------------

  async send(content) {
    const id = get().activeThreadId;
    const text = content.trim();
    if (!id || !text) return;
    if (get().running) {
      await api.steer(id, content);
      return;
    }
    // iOS-style instant echo: show the message immediately, reconcile on SSE echo.
    const tempId = `pending-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    set((s) => ({
      running: true,
      messages: [
        ...s.messages,
        { id: tempId, role: "user", content: text, tool_calls: [], pending: true } as ChatMessage,
      ],
    }));
    try {
      await api.sendMessage(id, content);
    } catch (err) {
      if (err instanceof ApiError && err.status === 0) {
        // Offline — queue for auto-send on reconnect, keep the echo visible.
        const item = { id: `out-${Date.now()}`, threadId: id, content, at: Date.now() };
        const outbox = [...get().outbox, item];
        saveOutbox(outbox);
        set((s) => ({
          running: false,
          outbox,
          messages: s.messages.map((m) => (m.id === tempId ? { ...m, pending: false } : m)),
        }));
        return;
      }
      // Roll back the optimistic message so the user can retry.
      set((s) => ({ running: false, messages: s.messages.filter((m) => m.id !== tempId) }));
      throw err;
    }
  },

  async flushOutbox() {
    const items = get().outbox;
    if (!items.length) return;
    for (const item of items) {
      try {
        if (get().activeThreadId !== item.threadId) {
          await get().selectThread(item.threadId);
        }
        // Send the existing queue item directly. Calling send() here would
        // create a second outbox item if the connection drops again.
        set({ running: true });
        await api.sendMessage(item.threadId, item.content);
        const rest = get().outbox.filter((o) => o.id !== item.id);
        saveOutbox(rest);
        set({ outbox: rest });
      } catch {
        set({ running: false });
        break; // still offline — retry on next reconnect
      }
    }
  },

  async interrupt() {
    const id = get().activeThreadId;
    if (!id) return;
    await api.interrupt(id);
  },

  async answerPermission(decision) {
    const { activeThreadId, permission } = get();
    if (!activeThreadId || !permission) return;
    set({ permission: null });
    await api.decidePermission(activeThreadId, permission.request_id, decision);
  },

  applyEvent(event) {
    const state = get();
    if (event.seq && event.seq <= state.lastSeq) return;
    const pushActivity = (item: Omit<ActivityItem, "at">) =>
      set((s) => ({ activity: [...s.activity.slice(-300), { ...item, at: Date.now() }] }));

    set({ lastSeq: event.seq ?? state.lastSeq });

    switch (event.type) {
      case "run_start": {
        set({
          running: true,
          activeProgress: { kind: "thinking", elapsed_s: 0, status: "thinking" },
          runMeta: {
            model: event.model as string,
            provider: event.provider as string,
            sandbox: event.sandbox as string,
            tools: event.tools as number,
          },
        });
        break;
      }
      case "run_end": {
        set({ running: false, activeProgress: null });
        void get().refreshThreads();
        try {
          if (
            get().notifyEnabled &&
            typeof document !== "undefined" &&
            document.hidden &&
            "Notification" in window &&
            Notification.permission === "granted"
          ) {
            new Notification("Rawal AI finished", {
              body: "Your agent run is complete — tap to view.",
              silent: true,
            });
          }
        } catch {
          /* notifications unavailable */
        }
        break;
      }
      case "message_start": {
        const role = (event.role as ChatMessage["role"]) ?? "assistant";
        const serverId = event.id as string;
        // Reconcile the optimistic echo: swap the pending message id for the real one.
        if (role === "user") {
          const pending = get().messages.find(
            (m) => m.role === "user" && m.pending && m.content === (event.content as string),
          );
          if (pending) {
            set((s) => ({
              messages: s.messages.map((m) =>
                m.id === pending.id
                  ? {
                      ...m,
                      id: serverId,
                      pending: false,
                      attachments: (event.attachments as ChatMessage["attachments"]) ?? m.attachments,
                    }
                  : m,
              ),
            }));
            break;
          }
        }
        set((s) => ({
          messages: upsertMessage(s.messages, serverId, {
            role,
            content: (event.content as string) ?? "",
            attachments: (event.attachments as ChatMessage["attachments"]) ?? [],
            streaming: role === "assistant",
            tool_calls: [],
          }),
        }));
        break;
      }
      case "text_delta": {
        set((s) => {
          const id = event.id as string;
          const existing = s.messages.find((m) => m.id === id);
          return {
            messages: upsertMessage(s.messages, id, {
              content: (existing?.content ?? "") + (event.text as string),
              streaming: true,
            }),
          };
        });
        break;
      }
      case "reasoning_delta": {
        set((s) => {
          const id = event.id as string;
          const existing = s.messages.find((m) => m.id === id);
          return {
            messages: upsertMessage(s.messages, id, {
              reasoning: (existing?.reasoning ?? "") + (event.text as string),
            }),
          };
        });
        break;
      }
      case "message_end": {
        set((s) => ({ messages: upsertMessage(s.messages, event.id as string, { streaming: false }) }));
        break;
      }
      case "thinking_progress": {
        set({
          activeProgress: {
            kind: "thinking",
            elapsed_s: Number(event.elapsed_s || 0),
            status: "thinking",
          },
        });
        break;
      }
      case "tool_call": {
        const call: ToolCall = {
          id: event.id as string,
          name: event.name as string,
          arguments: (event.arguments as Record<string, unknown>) ?? {},
          status: "running",
        };
        set((s) => {
          const messageId = event.message_id as string;
          const index = s.messages.findIndex((m) => m.id === messageId);
          if (index === -1) return s;
          const next = [...s.messages];
          next[index] = { ...next[index], tool_calls: [...next[index].tool_calls, call] };
          return {
            messages: next,
            activeProgress: {
              kind: "tool",
              name: call.name,
              elapsed_s: 0,
              status: "executing",
              id: call.id,
            },
          };
        });
        pushActivity({ id: call.id, kind: "tool", title: call.name, status: "running" });
        break;
      }
      case "tool_progress": {
        set({
          activeProgress: {
            kind: "tool",
            name: event.name as string,
            elapsed_s: Number(event.elapsed_s || 0),
            status: (event.status as string) || "executing",
            id: event.id as string,
          },
        });
        break;
      }
      case "tool_result": {
        set((s) => ({
          activeProgress: s.activeProgress?.id === event.id ? null : s.activeProgress,
          messages: patchToolCall(s.messages, event.id as string, {
            status: (event.status as ToolCall["status"]) ?? "ok",
            result: event.content as string,
            display: (event.display as ToolCall["display"]) ?? null,
            duration_ms: event.duration_ms as number,
          }),
          activity: s.activity.map((a) =>
            a.id === event.id ? { ...a, status: event.status as string } : a,
          ),
        }));
        const display = event.display as Record<string, unknown> | null;
        if (display && get().followAgent) {
          if (display.kind === "diff") {
            set({
              activeDiff: { path: display.path as string, diff: display.diff as string },
              computerTab: "editor",
            });
          } else if (display.kind === "file") {
            set({
              openFile: { path: display.path as string, content: display.content as string, dirty: false },
              computerTab: "editor",
            });
          } else if (display.kind === "agent_spawn" || display.kind === "agent_kill" || display.kind === "agent_kill_all") {
            void get().refreshSubAgents();
            set({ computerTab: "agents" });
          } else if (display.kind === "swarm_deploy" || display.kind === "swarm_kill") {
            void get().refreshSwarms();
            void get().refreshSubAgents();
            set({ computerTab: "agents" });
          }
        }
        break;
      }
      case "terminal_start": {
        set((s) => ({
          terminalLines: [...s.terminalLines, `\x1b[38;5;208m$\x1b[0m ${event.command as string}`],
          computerTab: s.followAgent ? "terminal" : s.computerTab,
        }));
        break;
      }
      case "terminal_output": {
        set((s) => ({ terminalLines: [...s.terminalLines.slice(-4000), event.chunk as string] }));
        break;
      }
      case "terminal_end": {
        set((s) => ({ terminalLines: [...s.terminalLines, ""] }));
        break;
      }
      case "todos": {
        set({ todos: (event.todos as Todo[]) ?? [] });
        break;
      }
      case "plan_mode_entered": {
        set((s) => ({ computerTab: s.followAgent ? "plan" : s.computerTab, computerOpen: true, planContent: null }));
        pushActivity({ id: `plan-${event.seq}`, kind: "note", title: "Entered Plan Mode", detail: event.reason as string });
        break;
      }
      case "plan_mode_exited": {
        set({ planContent: (event.plan as string) ?? "" });
        pushActivity({ id: `plan-exit-${event.seq}`, kind: "note", title: "Plan ready for approval" });
        break;
      }
      case "thinking": {
        pushActivity({ id: `think-${event.seq}`, kind: "thinking", title: "Thinking", detail: event.text as string });
        break;
      }
      case "skill": {
        const list = (event.skills as { name: string; mode: string }[] | undefined) ?? [];
        for (const skill of list) {
          const invoked = skill.mode === "invoked";
          pushActivity({
            id: `skill-${skill.name}-${event.seq}`,
            kind: "skill",
            title: `Using skill /${skill.name}`,
            detail: invoked
              ? "You invoked this skill — the agent is following it."
              : "Auto-loaded as relevant to this turn.",
          });
        }
        break;
      }
      case "artifact": {
        void get().refreshArtifacts();
        pushActivity({ id: `art-${event.seq}`, kind: "note", title: `Artifact: ${event.title as string}` });
        break;
      }
      case "preview": {
        // Never auto-open the Browser tab: heavy pages (games, big bundles)
        // would mount unasked and hang the UI. Stash the URL + note it; the
        // user opens Browser manually and loads it live then.
        set({ browserUrl: event.url as string });
        pushActivity({ id: `preview-${event.seq}`, kind: "note", title: "Preview ready — open the Browser tab to view it" });
        break;
      }
      case "browser_navigate": {
        set({ browserUrl: event.url as string });
        pushActivity({ id: `browser-${event.seq}`, kind: "note", title: "Browser link ready — open the Browser tab to view it" });
        break;
      }
      case "subagent_start": {
        pushActivity({
          id: `sub-${event.tool_call_id}`,
          kind: "subagent",
          title: `${event.agent_type as string}: ${event.description as string}`,
          status: "running",
        });
        break;
      }
      case "subagent_step": {
        set((s) => ({
          activity: s.activity.map((a) =>
            a.id === `sub-${event.tool_call_id}` ? { ...a, detail: `→ ${event.tool as string}` } : a,
          ),
        }));
        break;
      }
      case "subagent_end": {
        set((s) => ({
          activity: s.activity.map((a) =>
            a.id === `sub-${event.tool_call_id}` ? { ...a, status: event.ok ? "ok" : "error" } : a,
          ),
        }));
        break;
      }
      case "subagent_spawned": {
        pushActivity({
          id: `agent-${event.agent_id}`,
          kind: "subagent",
          title: `${event.agent_type as string}: ${event.name as string}`,
          status: "running",
          detail: `Priority: ${event.priority as string}`,
        });
        void get().refreshSubAgents();
        break;
      }
      case "subagent_status": {
        const agentStatus = event.status as string;
        const agentId = event.agent_id as string;
        set((s) => ({
          activity: s.activity.map((a) =>
            a.id === `agent-${agentId}` ? { ...a, status: agentStatus } : a,
          ),
        }));
        if (["completed", "failed", "killed"].includes(agentStatus)) {
          void get().refreshSubAgents();
        }
        break;
      }
      case "swarm_deployed": {
        pushActivity({
          id: `swarm-${event.swarm_id}`,
          kind: "subagent",
          title: `🐝 Swarm: ${event.name as string}`,
          status: "running",
          detail: `Strategy: ${event.strategy as string}, Agents: ${event.agent_count as number}`,
        });
        void get().refreshSwarms();
        void get().refreshSubAgents();
        break;
      }
      case "swarm_status": {
        const swarmStatus = event.status as string;
        const swarmId = event.swarm_id as string;
        set((s) => ({
          activity: s.activity.map((a) =>
            a.id === `swarm-${swarmId}` ? { ...a, status: swarmStatus } : a,
          ),
        }));
        if (["completed", "failed", "killed"].includes(swarmStatus)) {
          void get().refreshSwarms();
          void get().refreshSubAgents();
        }
        break;
      }
      case "permission_request": {
        set({ permission: event as unknown as PermissionRequest });
        break;
      }
      case "usage": {
        set({
          usage: {
            prompt_tokens: (event.prompt_tokens as number) ?? 0,
            completion_tokens: (event.completion_tokens as number) ?? 0,
          },
        });
        break;
      }
      case "compacted": {
        pushActivity({
          id: `compact-${event.seq}`,
          kind: "compaction",
          title: "Context compacted",
          detail: event.summary as string,
        });
        break;
      }
      case "title": {
        const id = get().activeThreadId;
        set((s) => ({
          threads: s.threads.map((t) => (t.id === id ? { ...t, title: event.title as string } : t)),
        }));
        break;
      }
      case "interrupted": {
        // The backend never sends message_end for the killed turn — settle
        // open streams here or the thinking animation spins forever.
        set((s) => ({ running: false, messages: settleStreaming(s.messages) }));
        pushActivity({ id: `int-${event.seq}`, kind: "note", title: "Stopped by you" });
        break;
      }
      case "error": {
        set((s) => ({ running: false, messages: settleStreaming(s.messages) }));
        pushActivity({
          id: `err-${event.seq}`,
          kind: "error",
          title: (event.kind as string) ?? "error",
          detail: event.message as string,
        });
        set((s) => ({
          messages: [
            ...s.messages,
            {
              id: `err-${event.seq}`,
              role: "assistant",
              content: "",
              error: event.message as string,
              tool_calls: [],
            },
          ],
        }));
        break;
      }
      default:
        break;
    }
  },

  // ---- agent computer --------------------------------------------------

  setComputerTab: (computerTab) => set({ computerTab, computerOpen: true }),
  toggleComputer: () => set((s) => ({ computerOpen: !s.computerOpen })),
  setFollowAgent: (followAgent) => set({ followAgent }),
  setLowPerf: (lowPerf) => {
    try {
      localStorage.setItem("bhati.lowperf", lowPerf ? "1" : "0");
    } catch {
      /* storage unavailable */
    }
    document.documentElement.classList.toggle("perf-low", lowPerf);
    set({ lowPerf });
  },

  setDeviceMode: (deviceMode) => {
    try {
      localStorage.setItem("bhati.deviceMode", deviceMode);
    } catch {
      /* storage unavailable */
    }
    const effective = deviceMode === "auto"
      ? (typeof window !== "undefined" && window.innerWidth < 768 ? "mobile" : "desktop")
      : deviceMode;
    set({ deviceMode, effectiveDeviceMode: effective });
  },

  setEffectiveDeviceMode: (effectiveDeviceMode) => set({ effectiveDeviceMode }),

  setNetworkMode: (networkMode) => {
    try {
      localStorage.setItem("bhati.networkMode", networkMode);
    } catch {
      /* storage unavailable */
    }
    const effective = networkMode === "auto"
      ? (get().networkStats.effectiveSpeedKbps <= 40 || get().networkStats.effectiveType === "slow-2g" || get().networkStats.effectiveType === "2g" ? "ultra_low" : "high_speed")
      : networkMode;
    document.documentElement.classList.toggle("perf-ultra-low", effective === "ultra_low");
    document.documentElement.classList.toggle("perf-high-speed", effective === "high_speed");
    set({ networkMode, effectiveNetworkMode: effective });
  },

  setEffectiveNetworkMode: (effectiveNetworkMode) => {
    document.documentElement.classList.toggle("perf-ultra-low", effectiveNetworkMode === "ultra_low");
    document.documentElement.classList.toggle("perf-high-speed", effectiveNetworkMode === "high_speed");
    set({ effectiveNetworkMode });
  },

  updateNetworkStats: (stats) => {
    set((s) => {
      const updated = { ...s.networkStats, ...stats };
      let effective = s.effectiveNetworkMode;
      if (s.networkMode === "auto") {
        effective = (updated.effectiveSpeedKbps <= 40 || updated.effectiveType === "slow-2g" || updated.effectiveType === "2g" || updated.rtt > 1500)
          ? "ultra_low"
          : "high_speed";
        document.documentElement.classList.toggle("perf-ultra-low", effective === "ultra_low");
        document.documentElement.classList.toggle("perf-high-speed", effective === "high_speed");
      }
      return { networkStats: updated, effectiveNetworkMode: effective };
    });
  },

  setWakeEnabled: (wakeEnabled) => {
    try {
      localStorage.setItem("bhati.wake", wakeEnabled ? "1" : "0");
    } catch {
      /* ignore */
    }
    set({ wakeEnabled });
  },

  setCallActive: (callActive) => set({ callActive }),
  setVoiceSettings: (settings) => {
    set(s => {
      if (settings.voiceEnabled !== undefined) localStorage.setItem('bhati.voice', String(settings.voiceEnabled));
      if (settings.voiceMode) localStorage.setItem('bhati.voiceMode', settings.voiceMode);
      if (settings.voiceTrigger) localStorage.setItem('bhati.voiceTrigger', settings.voiceTrigger);
      if (settings.voiceRate !== undefined) localStorage.setItem('bhati.voiceRate', String(settings.voiceRate));
      if (settings.voicePitch !== undefined) localStorage.setItem('bhati.voicePitch', String(settings.voicePitch));
      if (settings.translateMode !== undefined) localStorage.setItem('bhati.translateMode', settings.translateMode ? '1' : '0');
      if (settings.translateTarget) localStorage.setItem('bhati.translateTarget', settings.translateTarget);
      return { ...s, ...settings };
    });
  },

  async openPath(path) {
    const id = get().activeThreadId;
    if (!id) return;
    const file = await api.readFile(id, path);
    set({
      openFile: { path, content: file.content, dirty: false },
      activeDiff: null,
      computerTab: "editor",
    });
  },

  async saveOpenFile() {
    const id = get().activeThreadId;
    const file = get().openFile;
    if (!id || !file) return;
    try {
      await api.writeFile(id, file.path, file.content);
      set({ openFile: { ...file, dirty: false } });
    } catch (err) {
      // Keep dirty=true on failure so user can retry
      throw err;
    }
  },

  setOpenFileContent(content) {
    const file = get().openFile;
    if (!file) return;
    set({ openFile: { ...file, content, dirty: true } });
  },

  async refreshSandbox() {
    const id = get().activeThreadId;
    if (!id) return;
    set({ sandbox: await api.sandboxInfo(id).catch(() => null) });
  },

  async refreshArtifacts() {
    const id = get().activeThreadId;
    if (!id) return;
    set({ artifacts: await api.listArtifacts(id).catch(() => []) });
  },

  clearTerminal: () => set({ terminalLines: [] }),
  navigateBrowser: (url) => set({ browserUrl: url, computerTab: "browser", computerOpen: true }),
  closeBrowser: () => set({ browserUrl: null }),

  // ---- pro features --------------------------------------------------

  setDraft: (draft) => set({ draft }),
  consumeDraft: () => {
    const draft = get().draft;
    if (draft) set({ draft: null });
    return draft;
  },

  togglePin: (messageId) => {
    const id = get().activeThreadId;
    const pinnedIds = get().pinnedIds.includes(messageId)
      ? get().pinnedIds.filter((p) => p !== messageId)
      : [...get().pinnedIds, messageId];
    set({ pinnedIds });
    if (id) {
      try {
        localStorage.setItem(`bhati.pins.${id}`, JSON.stringify(pinnedIds));
      } catch {
        /* ignore */
      }
    }
  },

  async editResend(messageId, newContent) {
    const id = get().activeThreadId;
    if (!id || !newContent.trim() || get().running) return;
    await api.truncateThread(id, messageId);
    const idx = get().messages.findIndex((m) => m.id === messageId);
    set((s) => ({
      messages: (idx === -1 ? s.messages : s.messages.slice(0, idx)).filter((m) => !m.pending),
    }));
    await get().send(newContent);
  },

  async regenerate(messageId) {
    const state = get();
    const id = state.activeThreadId;
    if (!id || state.running) return;
    const idx = state.messages.findIndex((m) => m.id === messageId);
    if (idx === -1) return;
    const priorUser = [...state.messages.slice(0, idx)].reverse().find((m) => m.role === "user");
    if (!priorUser?.content.trim()) return;
    await api.truncateThread(id, messageId);
    set({ messages: state.messages.slice(0, idx) });
    await get().send(priorUser.content);
  },

  async forkFrom(messageId) {
    const id = get().activeThreadId;
    if (!id) return null;
    const thread = await api.forkThread(id, messageId ? { from_message_id: messageId } : {});
    set({ threads: [thread, ...get().threads] });
    await get().selectThread(thread.id);
    return thread;
  },

  setNotifyEnabled: (notifyEnabled) => {
    try {
      localStorage.setItem("bhati.notify", notifyEnabled ? "1" : "0");
    } catch {
      /* ignore */
    }
    if (notifyEnabled && "Notification" in window && Notification.permission === "default") {
      void Notification.requestPermission();
    }
    set({ notifyEnabled });
  },

  setAccentHue: (accentHue) => {
    try {
      if (accentHue === null) localStorage.removeItem("bhati.accentHue");
      else localStorage.setItem("bhati.accentHue", String(accentHue));
    } catch {
      /* ignore */
    }
    applyAccentHue(accentHue);
    set({ accentHue });
  },

  setKeymap: (partial) => {
    const keymap = { ...get().keymap, ...partial };
    try {
      localStorage.setItem(KEYMAP_KEY, JSON.stringify(keymap));
    } catch {
      /* ignore */
    }
    set({ keymap });
  },

  async setPin(pin) {
    if (!pin) {
      try {
        localStorage.removeItem("bhati.pinHash");
      } catch {
        /* ignore */
      }
      set({ lockHash: null, unlocked: true });
      return;
    }
    const lockHash = await sha256(pin);
    try {
      localStorage.setItem("bhati.pinHash", lockHash);
      sessionStorage.setItem("bhati.unlocked", "1");
    } catch {
      /* ignore */
    }
    set({ lockHash, unlocked: true });
  },

  async unlock(pin) {
    const lockHash = get().lockHash;
    if (!lockHash) {
      set({ unlocked: true });
      return true;
    }
    const ok = (await sha256(pin)) === lockHash;
    if (ok) {
      try {
        sessionStorage.setItem("bhati.unlocked", "1");
      } catch {
        /* ignore */
      }
      set({ unlocked: true });
    }
    return ok;
  },

  lockNow: () => {
    try {
      sessionStorage.removeItem("bhati.unlocked");
    } catch {
      /* ignore */
    }
    set({ unlocked: false });
  },

  setInstallEvt: (installEvt) => set({ installEvt }),

  async promptInstall() {
    const evt = get().installEvt as { prompt?: () => Promise<void> } | null;
    if (evt?.prompt) {
      await evt.prompt();
      set({ installEvt: null });
    }
  },

  // ---- agent management ----

  async refreshSubAgents() {
    const threadId = get().activeThreadId;
    if (!threadId) return;
    try {
      const agents = await api.listSubAgents(threadId);
      set({ subAgents: agents });
    } catch (e) {
      console.error("[AgentsPanel] refreshSubAgents failed:", e);
    }
  },

  async refreshSwarms() {
    const threadId = get().activeThreadId;
    if (!threadId) return;
    try {
      const swarms = await api.listSwarms(threadId);
      set({ swarms });
    } catch (e) {
      console.error("[AgentsPanel] refreshSwarms failed:", e);
    }
  },

  selectAgent(agentId) { set({ selectedAgentId: agentId }); },
  selectSwarm(swarmId) { set({ selectedSwarmId: swarmId }); },

  async spawnAgent(data) {
    const threadId = get().activeThreadId;
    if (!threadId) return;
    await api.spawnSubAgent(threadId, data);
    await get().refreshSubAgents();
  },

  async killAgent(agentId, force = false) {
    const threadId = get().activeThreadId;
    if (!threadId) return;
    await api.killSubAgent(threadId, agentId, force);
    await get().refreshSubAgents();
  },

  async killAllAgents() {
    const threadId = get().activeThreadId;
    if (!threadId) return;
    await api.killAllSubAgents(threadId);
    await get().refreshSubAgents();
  },

  async deploySwarmAction(data) {
    const threadId = get().activeThreadId;
    if (!threadId) return;
    await api.deploySwarm(threadId, data);
    await get().refreshSwarms();
    await get().refreshSubAgents();
  },

  async killSwarmAction(swarmId) {
    const threadId = get().activeThreadId;
    if (!threadId) return;
    await api.killSwarm(threadId, swarmId);
    await get().refreshSwarms();
    await get().refreshSubAgents();
  },
}));

export const activeThread = (state: State): Thread | undefined =>
  state.threads.find((t) => t.id === state.activeThreadId);

export const activeProject = (state: State): Project | undefined =>
  state.projects.find((p) => p.id === state.activeProjectId);
