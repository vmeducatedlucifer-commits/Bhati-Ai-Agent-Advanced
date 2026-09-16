/** Custom voice commands: spoken phrase → expanded agent prompt. */

export interface VoiceShortcut {
  id: string;
  phrase: string;
  action: string;
}

const KEY = "bhati.voiceShortcuts";

export const DEFAULT_SHORTCUTS: VoiceShortcut[] = [
  {
    id: "deploy",
    phrase: "deploy kar do",
    action:
      "Push the workspace to GitHub, then deploy the frontend on Vercel and verify the backend is live, following the standard deploy flow. Execute everything you can directly and report URLs.",
  },
  {
    id: "deploy-en",
    phrase: "deploy it",
    action:
      "Push the workspace to GitHub, then deploy the frontend on Vercel and verify the backend is live, following the standard deploy flow. Execute everything you can directly and report URLs.",
  },
  {
    id: "test",
    phrase: "test chala do",
    action: "Run the project's full test suite now and report the results. If anything fails, fix it.",
  },
  {
    id: "review",
    phrase: "code review karo",
    action:
      "Review the recent workspace changes for bugs, security issues and code smells. Report file:line findings with severity.",
  },
  {
    id: "status",
    phrase: "status batao",
    action: "Summarize the current project status: what works, what is pending, and suggested next steps.",
  },
];

export function loadShortcuts(): VoiceShortcut[] {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) {
      localStorage.setItem(KEY, JSON.stringify(DEFAULT_SHORTCUTS));
      return [...DEFAULT_SHORTCUTS];
    }
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [...DEFAULT_SHORTCUTS];
  } catch {
    return [...DEFAULT_SHORTCUTS];
  }
}

export function saveShortcuts(list: VoiceShortcut[]): void {
  try {
    localStorage.setItem(KEY, JSON.stringify(list));
  } catch {
    /* ignore */
  }
}

/** Returns the expanded action when the transcript contains a shortcut phrase. */
export function matchShortcut(text: string): string | null {
  const heard = text.toLowerCase().trim();
  if (!heard) return null;
  for (const s of loadShortcuts()) {
    if (s.phrase && heard.includes(s.phrase.toLowerCase())) return s.action;
  }
  return null;
}
