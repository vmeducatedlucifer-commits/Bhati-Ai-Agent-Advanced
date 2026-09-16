import {
  Archive,
  Bell,
  FolderPlus,
  Gauge,
  Lock,
  MessageSquarePlus,
  Moon,
  PanelRightClose,
  Search,
  Settings,
  Trash,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { api } from "@/lib/api";
import { useStore } from "@/lib/store";

interface Action {
  id: string;
  label: string;
  hint?: string;
  icon: typeof Search;
  run: () => void;
}

export function CommandPalette({
  open,
  onOpenChange,
  onOpenSettings,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  onOpenSettings: () => void;
}) {
  const [query, setQuery] = useState("");
  const projects = useStore((s) => s.projects);
  const threads = useStore((s) => s.threads);
  const activeProjectId = useStore((s) => s.activeProjectId);
  const activeThreadId = useStore((s) => s.activeThreadId);
  const selectProject = useStore((s) => s.selectProject);
  const selectThread = useStore((s) => s.selectThread);
  const createThread = useStore((s) => s.createThread);
  const toggleComputer = useStore((s) => s.toggleComputer);
  const setLowPerf = useStore((s) => s.setLowPerf);
  const lowPerf = useStore((s) => s.lowPerf);
  const lockNow = useStore((s) => s.lockNow);
  const lockHash = useStore((s) => s.lockHash);
  const activeThread = threads.find((t) => t.id === activeThreadId);

  useEffect(() => {
    if (open) setQuery("");
  }, [open ]);

  const close = () => onOpenChange(false);

  const actions: Action[] = useMemo(() => {
    const list: Action[] = [
      {
        id: "new-chat",
        label: "New chat",
        hint: "current project",
        icon: MessageSquarePlus,
        run: () => activeProjectId && void createThread(activeProjectId),
      },
      {
        id: "toggle-computer",
        label: "Toggle agent computer",
        icon: PanelRightClose,
        run: () => toggleComputer(),
      },
      {
        id: "perf",
        label: lowPerf ? "Disable performance mode" : "Enable performance mode",
        icon: Gauge,
        run: () => setLowPerf(!lowPerf),
      },
      {
        id: "settings",
        label: "Open settings",
        icon: Settings,
        run: () => onOpenSettings(),
      },
      {
        id: "dl-zip",
        label: "Download project ZIP",
        icon: Archive,
        run: () => {
          const p = projects.find((x) => x.id === activeProjectId);
          if (p) void api.downloadProjectZip(p.id, `${p.name}.zip`);
        },
      },
    ];
    if (activeThread) {
      list.push({
        id: "clear-chat",
        label: `Clear “${activeThread.title}”`,
        icon: Trash,
        run: () => {
          void api.clearMessages(activeThread.id).then(() => void selectThread(activeThread.id));
        },
      });
    }
    if (lockHash) {
      list.push({ id: "lock", label: "Lock app now", icon: Lock, run: () => lockNow() });
    }
    for (const p of projects.slice(0, 6)) {
      if (p.id === activeProjectId) continue;
      list.push({
        id: `proj-${p.id}`,
        label: `Switch to ${p.name}`,
        hint: "project",
        icon: FolderPlus,
        run: () => void selectProject(p.id),
      });
    }
    for (const t of threads.slice(0, 6)) {
      if (t.id === activeThreadId) continue;
      list.push({
        id: `thread-${t.id}`,
        label: t.title,
        hint: "chat",
        icon: MessageSquarePlus,
        run: () => void selectThread(t.id),
      });
    }
    return list;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, projects, threads, activeProjectId, activeThreadId, lowPerf]);

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return actions;
    return actions.filter((a) => `${a.label} ${a.hint ?? ""}`.toLowerCase().includes(needle));
  }, [actions, query]);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="top-[18%] w-[min(560px,94vw)] translate-y-0 gap-2 p-2 animate-pop-in">
        <div className="flex items-center gap-2 rounded-lg border border-border bg-surface px-3">
          <Search className="size-4 shrink-0 text-muted-foreground" />
          <input
            autoFocus
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && filtered[0]) {
                filtered[0].run();
                close();
              }
            }}
            placeholder="Type a command or search…"
            className="h-11 w-full bg-transparent text-[14px] focus:outline-none"
          />
          <kbd className="rounded bg-muted px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground">ESC</kbd>
        </div>
        <ul className="scrollbar-thin max-h-72 overflow-y-auto">
          {filtered.map((a) => (
            <li key={a.id}>
              <button
                type="button"
                onClick={() => {
                  a.run();
                  close();
                }}
                className="flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-left text-[13.5px] transition-colors hover:bg-accent"
              >
                <a.icon className="size-4 shrink-0 text-primary" />
                <span className="min-w-0 flex-1 truncate">{a.label}</span>
                {a.hint ? <span className="text-[11px] text-muted-foreground">{a.hint}</span> : null}
              </button>
            </li>
          ))}
          {filtered.length === 0 ? (
            <p className="flex items-center gap-2 px-3 py-4 text-[13px] text-muted-foreground">
              <Bell className="size-4" />
              No matching commands.
            </p>
          ) : null}
        </ul>
        <p className="flex items-center gap-1 px-2 pb-1 text-[10.5px] text-muted-foreground">
          <Moon className="size-3" />
          Tip: press Ctrl+K anywhere to open this palette.
        </p>
      </DialogContent>
    </Dialog>
  );
}
