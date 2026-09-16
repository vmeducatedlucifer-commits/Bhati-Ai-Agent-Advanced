import {
  Folder,
  FolderPlus,
  MessageSquare,
  Plus,
  Trash2,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { hapticLight, hapticMedium } from "@/lib/haptics";
import { activeProject, useStore } from "@/lib/store";

interface MobileProjectsViewProps {
  onNewProject: () => void;
  onSelectProject?: () => void;
}

export function MobileProjectsView({ onNewProject, onSelectProject }: MobileProjectsViewProps) {
  const projects = useStore((s) => s.projects);
  const threads = useStore((s) => s.threads);
  const activeProjectId = useStore((s) => s.activeProjectId);
  const activeThreadId = useStore((s) => s.activeThreadId);
  const selectProject = useStore((s) => s.selectProject);
  const selectThread = useStore((s) => s.selectThread);
  const createThread = useStore((s) => s.createThread);
  const deleteThread = useStore((s) => s.deleteThread);

  const currentProject = useStore(activeProject);

  const handleSelectProject = async (id: string) => {
    hapticLight();
    await selectProject(id);
    if (onSelectProject) onSelectProject();
  };

  const handleCreateThread = async () => {
    if (!activeProjectId) return;
    hapticMedium();
    await createThread(activeProjectId);
    if (onSelectProject) onSelectProject();
  };

  return (
    <div className="flex h-full flex-col bg-background pb-18">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-border bg-surface px-3.5 py-3 shadow-xs">
        <div className="flex items-center gap-2">
          <div className="flex size-7 items-center justify-center rounded-lg bg-primary/10 text-primary">
            <Folder className="size-4" />
          </div>
          <h2 className="text-sm font-bold text-foreground">Projects & Workspaces</h2>
        </div>
        <Button
          variant="outline"
          size="xs"
          onClick={() => {
            hapticLight();
            onNewProject();
          }}
          className="gap-1 text-xs rounded-full"
        >
          <FolderPlus className="size-3.5 text-primary" />
          <span>New Project</span>
        </Button>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto p-3.5 space-y-5">
        {/* Projects Cards Carousel / List */}
        <div>
          <div className="mb-2 flex items-center justify-between px-1">
            <span className="text-[11px] font-bold uppercase tracking-wider text-muted-foreground">
              Projects ({projects.length})
            </span>
          </div>
          <div className="grid grid-cols-1 gap-2">
            {projects.map((p) => {
              const isActive = p.id === activeProjectId;
              return (
                <button
                  key={p.id}
                  type="button"
                  onClick={() => void handleSelectProject(p.id)}
                  className={`flex w-full items-center justify-between rounded-xl border p-3 text-left transition-all active:scale-[0.98] ${
                    isActive
                      ? "border-primary/60 bg-primary/10 shadow-sm"
                      : "border-border/80 bg-surface hover:bg-muted/40"
                  }`}
                >
                  <div className="flex min-w-0 items-center gap-3">
                    <div
                      className={`flex size-9 shrink-0 items-center justify-center rounded-lg ${
                        isActive ? "bg-primary text-primary-foreground" : "bg-muted text-muted-foreground"
                      }`}
                    >
                      <Folder className="size-4.5" />
                    </div>
                    <div className="min-w-0 flex-1">
                      <span className={`block truncate text-xs font-bold ${isActive ? "text-primary" : "text-foreground"}`}>
                        {p.name}
                      </span>
                      <span className="block truncate text-[10.5px] text-muted-foreground">
                        {p.description || "Workspace Sandbox"}
                      </span>
                    </div>
                  </div>
                  {isActive && (
                    <span className="rounded-full bg-primary/20 px-2 py-0.5 text-[10px] font-bold text-primary">
                      Active
                    </span>
                  )}
                </button>
              );
            })}
          </div>
        </div>

        {/* Current Project's Chats / Sessions */}
        {currentProject && (
          <div>
            <div className="mb-2 flex items-center justify-between px-1">
              <span className="text-[11px] font-bold uppercase tracking-wider text-muted-foreground">
                Sessions in {currentProject.name}
              </span>
              <button
                type="button"
                onClick={() => void handleCreateThread()}
                className="flex items-center gap-1 rounded-full bg-primary/15 px-2.5 py-1 text-[11px] font-bold text-primary active:scale-95 transition"
              >
                <Plus className="size-3" />
                <span>New Chat</span>
              </button>
            </div>
            <div className="space-y-1.5">
              {threads.length === 0 ? (
                <div className="rounded-xl border border-dashed border-border p-6 text-center text-xs text-muted-foreground">
                  <MessageSquare className="mx-auto size-6 opacity-30 mb-2" />
                  <p>No chat sessions yet in this project.</p>
                  <button
                    type="button"
                    onClick={() => void handleCreateThread()}
                    className="mt-2 inline-flex items-center gap-1 text-xs font-bold text-primary hover:underline"
                  >
                    Start a new chat
                  </button>
                </div>
              ) : (
                threads.map((t) => {
                  const isActive = t.id === activeThreadId;
                  return (
                    <div
                      key={t.id}
                      className={`group flex items-center justify-between rounded-xl border px-3.5 py-2.5 text-xs transition-all active:scale-[0.99] ${
                        isActive
                          ? "border-primary/50 bg-primary/10 font-bold"
                          : "border-border/70 bg-surface hover:bg-muted/30"
                      }`}
                    >
                      <button
                        type="button"
                        onClick={() => {
                          hapticLight();
                          void selectThread(t.id);
                          if (onSelectProject) onSelectProject();
                        }}
                        className="flex min-w-0 flex-1 items-center gap-2.5 text-left"
                      >
                        <MessageSquare className={`size-4 shrink-0 ${isActive ? "text-primary" : "text-muted-foreground"}`} />
                        <span className={`truncate text-xs ${isActive ? "text-primary" : "text-foreground"}`}>
                          {t.title}
                        </span>
                      </button>
                      <Button
                        variant="ghost"
                        size="xs"
                        onClick={() => {
                          hapticLight();
                          void deleteThread(t.id);
                        }}
                        className="size-7 text-muted-foreground hover:text-danger shrink-0"
                        title="Delete chat"
                      >
                        <Trash2 className="size-3.5" />
                      </Button>
                    </div>
                  );
                })
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
