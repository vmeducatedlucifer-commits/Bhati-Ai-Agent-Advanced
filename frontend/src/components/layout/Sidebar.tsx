import {
  Archive,
  ChevronsUpDown,
  Download,
  FileText,
  FolderPlus,
  GitFork,
  History,
  MessageCircle,
  MessageSquarePlus,
  MonitorDown,
  MoreHorizontal,
  Search,
  Settings,
  Trash2,
} from "lucide-react";
import { useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown";
import { Input } from "@/components/ui/input";
import { Tooltip } from "@/components/ui/primitives";
import { api, displayModelName } from "@/lib/api";
import { useStore } from "@/lib/store";
import { cn, groupByDay, relativeTime } from "@/lib/utils";
import { ReplayDialog } from "@/components/chat/ReplayDialog";

export function Sidebar({
  onOpenSettings,
  onNewProject,
}: {
  onOpenSettings: () => void;
  onNewProject: () => void;
}) {
  const projects = useStore((s) => s.projects);
  const threads = useStore((s) => s.threads);
  const activeProjectId = useStore((s) => s.activeProjectId);
  const activeThreadId = useStore((s) => s.activeThreadId);
  const selectProject = useStore((s) => s.selectProject);
  const selectThread = useStore((s) => s.selectThread);
  const createThread = useStore((s) => s.createThread);
  const deleteThread = useStore((s) => s.deleteThread);
  const deleteProject = useStore((s) => s.deleteProject);
  const forkFrom = useStore((s) => s.forkFrom);
  const canInstall = useStore((s) => s.installEvt !== null);
  const promptInstall = useStore((s) => s.promptInstall);

  const [query, setQuery] = useState("");
  const [replayThread, setReplayThread] = useState<{ id: string; title: string } | null>(null);
  const project = projects.find((p) => p.id === activeProjectId);

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return threads;
    return threads.filter((t) => t.title.toLowerCase().includes(needle));
  }, [threads, query]);

  const grouped = useMemo(
    () => groupByDay(filtered, (t) => t.last_message_at ?? t.updated_at),
    [filtered],
  );

  const exportThread = async (threadId: string, title: string) => {
    try {
      const messages = await api.listMessages(threadId);
      const markdown = messages
        .map((m) => `### ${m.role.toUpperCase()}\n\n${m.content}\n\n---\n`)
        .join("\n");
      const blob = new Blob([markdown], { type: "text/markdown" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${title.replace(/[^a-zA-Z0-9_-]/g, "_")}.md`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      console.error("Export failed", e);
    }
  };

  const exportPdf = async (threadId: string, title: string) => {
    try {
      const messages = await api.listMessages(threadId);
      const safe = (s: string) =>
        s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
      const rows = messages
        .map(
          (m) =>
            `<div style="margin:14px 0"><div style="font:600 11px sans-serif;color:#888;text-transform:uppercase">${m.role}</div><div style="font:14px/1.7 sans-serif;white-space:pre-wrap">${safe(m.content || "(no text)")}</div></div><hr/>`,
        )
        .join("");
      const win = window.open("", "_blank");
      if (!win) return;
      win.document.write(
        `<html><head><title>${safe(title)}</title><style>@media print{body{margin:24px}}</style></head><body><h1 style="font-family:sans-serif">${safe(title)}</h1>${rows}<script>window.onload=()=>window.print()</script></body></html>`,
      );
      win.document.close();
    } catch (e) {
      console.error("PDF export failed", e);
    }
  };

  const downloadProject = async (projectId: string, name: string) => {
    try {
      await api.downloadProjectZip(projectId, `${name.replace(/[^a-zA-Z0-9_-]/g, "_")}.zip`);
    } catch (e) {
      console.error("Project download failed", e);
    }
  };

  const removeProject = async (projectId: string, name: string) => {
    if (!confirm(`Delete project "${name}"?\n\nThis removes all its chats AND every workspace file permanently.`)) return;
    try {
      await deleteProject(projectId);
    } catch (e) {
      console.error("Project delete failed", e);
    }
  };

  return (
    <aside className="liquid-bar flex h-full w-full flex-col">
      <div className="p-2.5">
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <button
              type="button"
              className="flex w-full items-center gap-2 rounded-lg px-2 py-2 text-left transition-colors hover:bg-accent"
            >
              <span className="flex size-7 shrink-0 items-center justify-center rounded-md bg-primary text-[13px] font-semibold text-primary-foreground">
                {(project?.name ?? "R").slice(0, 1).toUpperCase()}
              </span>
              <span className="min-w-0 flex-1">
                <span className="block truncate text-[13px] font-medium">
                  {project?.name ?? "No project"}
                </span>
                <span className="block truncate text-[11px] text-muted-foreground">
                  {project
                    ? `${project.thread_count} chat${project.thread_count === 1 ? "" : "s"}`
                    : "Create one to start"}
                </span>
              </span>
              <ChevronsUpDown className="size-3.5 shrink-0 text-muted-foreground" />
            </button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="start" className="w-64">
            <DropdownMenuLabel>Projects</DropdownMenuLabel>
            {projects.map((p) => (
              <DropdownMenuItem key={p.id} onSelect={() => void selectProject(p.id)}>
                <span className="flex size-5 items-center justify-center rounded bg-muted text-[10px] font-semibold">
                  {p.name.slice(0, 1).toUpperCase()}
                </span>
                <span className="truncate">{p.name}</span>
              </DropdownMenuItem>
            ))}
            <DropdownMenuSeparator />
            <DropdownMenuItem onSelect={onNewProject}>
              <FolderPlus className="size-4" />
              New project
            </DropdownMenuItem>
            {project ? (
              <>
                <DropdownMenuSeparator />
                <DropdownMenuLabel>Current project</DropdownMenuLabel>
                <DropdownMenuItem onSelect={() => void downloadProject(project.id, project.name)}>
                  <Archive className="size-4" />
                  Download project ZIP
                </DropdownMenuItem>
                <DropdownMenuItem
                  destructive
                  onSelect={() => void removeProject(project.id, project.name)}
                >
                  <Trash2 className="size-4" />
                  Delete project
                </DropdownMenuItem>
              </>
            ) : null}
          </DropdownMenuContent>
        </DropdownMenu>
      </div>

      <div className="space-y-2 px-2.5 pb-2">
        <Button
          className="w-full justify-start"
          size="sm"
          disabled={!activeProjectId}
          onClick={() => activeProjectId && void createThread(activeProjectId)}
        >
          <MessageSquarePlus className="size-4" />
          New chat
        </Button>
        <div className="relative">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search chats"
            className="h-8 bg-transparent pl-8 text-[13px]"
          />
        </div>
      </div>

      <nav className="scrollbar-thin min-h-0 flex-1 overflow-y-auto px-2 pb-2">
        {grouped.length === 0 ? (
          <p className="px-2 py-6 text-center text-[12.5px] text-muted-foreground">
            {query ? "No matching chats." : "No chats yet."}
          </p>
        ) : (
          grouped.map(([label, items]) => (
            <div key={label} className="mb-2">
              <p className="px-2 py-1 text-[10.5px] font-medium uppercase tracking-wide text-muted-foreground">
                {label}
              </p>
              {items.map((thread) => (
                <div
                  key={thread.id}
                  className={cn(
                    "group flex items-center gap-1 rounded-lg px-2 py-1.5 transition-colors hover:bg-accent",
                    activeThreadId === thread.id && "bg-accent",
                  )}
                >
                  <button
                    type="button"
                    onClick={() => void selectThread(thread.id)}
                    className="min-w-0 flex-1 text-left"
                  >
                    <span className="flex items-center gap-1.5">
                      {thread.status === "running" && (
                        <span className="size-1.5 shrink-0 animate-pulse rounded-full bg-primary" />
                      )}
                      {thread.source === "telegram" && (
                        <MessageCircle className="size-3.5 shrink-0 text-sky-400" />
                      )}
                      <span className="truncate text-[13px]">{thread.title}</span>
                    </span>
                    <span className="block truncate text-[10.5px] text-muted-foreground">
                      {thread.source === "telegram" ? "Telegram · " : ""}
                      {relativeTime(thread.last_message_at ?? thread.updated_at)}
                      {thread.model ? ` · ${displayModelName(thread.model)}` : ""}
                    </span>
                  </button>
                  <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                      <button
                        type="button"
                        title="Chat actions"
                        aria-label={`Actions for ${thread.title}`}
                        className="reveal-on-hover rounded p-1 text-muted-foreground opacity-0 transition-opacity hover:text-foreground focus-visible:opacity-100 group-focus-within:opacity-100 group-hover:opacity-100 data-[state=open]:opacity-100"
                      >
                        <MoreHorizontal className="size-3.5" />
                      </button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end">
                      <DropdownMenuItem
                        onSelect={() => void exportThread(thread.id, thread.title)}
                      >
                        <Download className="size-4" />
                        Export Markdown
                      </DropdownMenuItem>
                      <DropdownMenuItem
                        onSelect={() => void exportPdf(thread.id, thread.title)}
                      >
                        <FileText className="size-4" />
                        Export PDF
                      </DropdownMenuItem>
                      <DropdownMenuItem
                        onSelect={() => {
                          void selectThread(thread.id).then(() => void forkFrom());
                        }}
                      >
                        <GitFork className="size-4" />
                        Fork chat
                      </DropdownMenuItem>
                      <DropdownMenuItem
                        onSelect={() => setReplayThread({ id: thread.id, title: thread.title })}
                      >
                        <History className="size-4" />
                        Replay run
                      </DropdownMenuItem>
                      <DropdownMenuItem
                        destructive
                        onSelect={() => void deleteThread(thread.id)}
                      >
                        <Trash2 className="size-4" />
                        Delete chat
                      </DropdownMenuItem>
                    </DropdownMenuContent>
                  </DropdownMenu>
                </div>
              ))}
            </div>
          ))
        )}
      </nav>

      <div className="flex items-center gap-1 border-t border-border p-2">
        {canInstall ? (
          <Tooltip content="Install as desktop / mobile app">
            <Button variant="ghost" size="sm" className="flex-1 justify-start" onClick={() => void promptInstall()}>
              <MonitorDown className="size-4" />
              Install app
            </Button>
          </Tooltip>
        ) : null}
        <Tooltip content="Settings">
          <Button variant="ghost" size="sm" className="flex-1 justify-start" onClick={onOpenSettings}>
            <Settings className="size-4" />
            Settings
          </Button>
        </Tooltip>
      </div>

      <ReplayDialog
        open={replayThread !== null}
        onOpenChange={(v) => !v && setReplayThread(null)}
        threadId={replayThread?.id ?? null}
        threadTitle={replayThread?.title ?? ""}
      />
    </aside>
  );
}
