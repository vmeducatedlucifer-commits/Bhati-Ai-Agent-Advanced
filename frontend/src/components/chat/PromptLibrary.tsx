import { BookMarked, Plus, Trash2, Users, User } from "lucide-react";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { api } from "@/lib/api";
import { useStore } from "@/lib/store";
import { cn } from "@/lib/utils";

interface SavedPrompt {
  id: string;
  title: string;
  body: string;
}

const PERSONAL_KEY = "rawal.prompts";
const TEAM_PATH = ".agent/prompts.json";

const PERSONAS: { name: string; mode: "agent" | "plan" | "chat"; system: string }[] = [
  {
    name: "Senior Engineer",
    mode: "agent",
    system: "You are a senior staff engineer. Prefer the simplest correct solution, write tests for new logic, keep functions small, and explain trade-offs briefly.",
  },
  {
    name: "Code Reviewer",
    mode: "plan",
    system: "You are a strict but fair code reviewer. Investigate read-only, find bugs, security issues and smells. Report findings with file:line references and severity. Do not write code unless asked.",
  },
  {
    name: "DevOps Engineer",
    mode: "agent",
    system: "You are a DevOps engineer. You handle Docker, CI/CD, deployments and infra. Always verify with builds/tests, keep images small, never expose secrets.",
  },
  {
    name: "Teacher (Hindi + English)",
    mode: "chat",
    system: "You are a friendly teacher. Explain simply in Hindi mixed with English (Hinglish), use small examples, and ask one check-in question at the end.",
  },
  {
    name: "Security Auditor",
    mode: "plan",
    system: "You are a security auditor. Hunt for injection, auth, secret-leak and dependency risks. Rank by severity with concrete fixes. Read-only unless asked to patch.",
  },
];

function loadPersonal(): SavedPrompt[] {
  try {
    const raw = localStorage.getItem(PERSONAL_KEY);
    return raw ? JSON.parse(raw) : [];
  } catch {
    return [];
  }
}

export function PromptLibrary({
  open,
  onOpenChange,
  onInsert,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  onInsert: (body: string) => void;
}) {
  const threadId = useStore((s) => s.activeThreadId);
  const refreshThreads = useStore((s) => s.refreshThreads);
  const [tab, setTab] = useState<"personal" | "team" | "personas">("personal");
  const [personal, setPersonal] = useState<SavedPrompt[]>(loadPersonal);
  const [team, setTeam] = useState<SavedPrompt[]>([]);
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [applied, setApplied] = useState<string | null>(null);

  useEffect(() => {
    if (!open || !threadId) return;
    api
      .readFile(threadId, TEAM_PATH)
      .then((f) => {
        try {
          const parsed = JSON.parse(f.content);
          setTeam(Array.isArray(parsed) ? parsed : []);
        } catch {
          setTeam([]);
        }
      })
      .catch(() => setTeam([]));
  }, [open, threadId]);

  const savePersonal = (list: SavedPrompt[]) => {
    setPersonal(list);
    try {
      localStorage.setItem(PERSONAL_KEY, JSON.stringify(list));
    } catch {
      /* ignore */
    }
  };

  const saveTeam = async (list: SavedPrompt[]) => {
    if (!threadId) return;
    setTeam(list);
    await api.writeFile(threadId, TEAM_PATH, JSON.stringify(list, null, 2)).catch(() => {});
  };

  const applyPersona = async (name: string, mode: "agent" | "plan" | "chat", system: string) => {
    if (!threadId) return;
    await api.updateThread(threadId, { system_prompt: system, mode });
    await refreshThreads();
    setApplied(name);
    setTimeout(() => setApplied(null), 1800);
  };

  const list = tab === "personal" ? personal : team;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[84vh] w-[min(560px,94vw)] overflow-y-auto scrollbar-thin">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <BookMarked className="size-4 text-primary" />
            Prompt Library & Personas
          </DialogTitle>
        </DialogHeader>

        <div className="mb-3 flex gap-1 rounded-lg bg-muted p-1">
          {(
            [
              ["personal", "Personal", User],
              ["team", "Team", Users],
              ["personas", "Personas", BookMarked],
            ] as const
          ).map(([key, label, Icon]) => (
            <button
              key={key}
              type="button"
              onClick={() => setTab(key)}
              className={cn(
                "flex flex-1 items-center justify-center gap-1.5 rounded-md px-2 py-1.5 text-[12.5px] font-medium transition-colors",
                tab === key ? "bg-surface text-foreground shadow-sm" : "text-muted-foreground",
              )}
            >
              <Icon className="size-3.5" />
              {label}
            </button>
          ))}
        </div>

        {tab === "personas" ? (
          <ul className="space-y-2">
            {PERSONAS.map((p) => (
              <li key={p.name} className="lift rounded-xl border border-border bg-surface p-3">
                <div className="flex items-center gap-2">
                  <p className="flex-1 text-[13px] font-medium">{p.name}</p>
                  <span className="rounded-full bg-muted px-2 py-0.5 font-mono text-[10.5px] text-muted-foreground">
                    {p.mode}
                  </span>
                  <Button size="xs" variant="outline" disabled={!threadId} onClick={() => void applyPersona(p.name, p.mode, p.system)}>
                    {applied === p.name ? "Applied ✓" : "Apply"}
                  </Button>
                </div>
                <p className="mt-1 line-clamp-2 text-[12px] text-muted-foreground">{p.system}</p>
              </li>
            ))}
          </ul>
        ) : (
          <>
            <ul className="space-y-2">
              {list.map((p) => (
                <li key={p.id} className="rounded-xl border border-border bg-surface p-3">
                  <div className="flex items-center gap-2">
                    <p className="flex-1 truncate text-[13px] font-medium">{p.title}</p>
                    <Button
                      size="xs"
                      variant="ghost"
                      onClick={() => {
                        const next = list.filter((x) => x.id !== p.id);
                        if (tab === "personal") savePersonal(next);
                        else void saveTeam(next);
                      }}
                    >
                      <Trash2 className="size-3.5 text-danger" />
                    </Button>
                    <Button
                      size="xs"
                      onClick={() => {
                        onInsert(p.body);
                        onOpenChange(false);
                      }}
                    >
                      Insert
                    </Button>
                  </div>
                  <p className="mt-1 line-clamp-2 whitespace-pre-wrap text-[12px] text-muted-foreground">{p.body}</p>
                </li>
              ))}
              {list.length === 0 ? (
                <p className="py-4 text-center text-[12.5px] text-muted-foreground">
                  {tab === "personal" ? "No saved prompts yet." : "No team prompts — they live in .agent/prompts.json"}
                </p>
              ) : null}
            </ul>

            <div className="mt-3 space-y-2 rounded-xl border border-dashed border-border p-3">
              <Input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Prompt title" className="h-8 text-xs" />
              <textarea
                value={body}
                onChange={(e) => setBody(e.target.value)}
                rows={3}
                placeholder="Prompt body…"
                className="w-full rounded-lg border border-input bg-surface px-3 py-2 text-[12.5px] focus:outline-none"
              />
              <Button
                size="sm"
                disabled={!title.trim() || !body.trim()}
                onClick={() => {
                  const item = { id: `p-${Date.now()}`, title: title.trim(), body: body.trim() };
                  if (tab === "personal") savePersonal([...personal, item]);
                  else void saveTeam([...team, item]);
                  setTitle("");
                  setBody("");
                }}
              >
                <Plus className="size-3.5" />
                Save to {tab}
              </Button>
            </div>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}
