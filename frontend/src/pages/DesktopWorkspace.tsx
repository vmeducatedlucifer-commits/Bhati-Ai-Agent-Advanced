import { Bot, Boxes, FolderPlus, Globe2, PanelLeftClose, PanelLeftOpen, Rocket, Sparkles, TerminalSquare } from "lucide-react";
import { useEffect, useState } from "react";
import { ChatPanel } from "@/components/chat/ChatPanel";
import { CommandPalette } from "@/components/layout/CommandPalette";
import { ComputerPanel } from "@/components/computer/ComputerPanel";
import { SplitPane } from "@/components/layout/SplitPane";
import { Sidebar } from "@/components/layout/Sidebar";
import { TopBar } from "@/components/layout/TopBar";
import { ShortcutsDialog } from "@/components/layout/ShortcutsDialog";
import { NewProjectDialog } from "@/components/projects/NewProjectDialog";
import { SettingsDialog } from "@/components/settings/SettingsDialog";
import { CallMode } from "@/components/voice/CallMode";
import { Button } from "@/components/ui/button";
import { useEventStream } from "@/hooks/useEventStream";
import { useVoiceAssistant } from "@/hooks/useVoiceAssistant";
import { useStore } from "@/lib/store";
import { cn } from "@/lib/utils";

const FIRST_RUN_PILLS = [
  { icon: TerminalSquare, label: "Isolated Linux sandbox" },
  { icon: Globe2, label: "Research + browser tools" },
  { icon: Rocket, label: "Preview and ship" },
];

const QUICK_STARTS = [
  { icon: Boxes, title: "Build an app", description: "Turn an idea into a polished, working product.", name: "Product workspace", prompt: "Build a production-ready web app from my requirements. Start by asking the smallest set of clarifying questions, then plan, implement, test, and show me the preview." },
  { icon: Globe2, title: "Research and decide", description: "Compare sources and produce an actionable brief.", name: "Research workspace", prompt: "Research a topic deeply, compare credible sources, and turn the findings into a concise decision brief with citations and next steps." },
  { icon: Bot, title: "Automate a workflow", description: "Design a repeatable agent workflow with guardrails.", name: "Automation workspace", prompt: "Help me design and implement a reliable automation workflow. Identify triggers, actions, integrations, failure handling, and a safe test plan before building it." },
];

function FirstRun({ onNewProject }: { onNewProject: (template?: { name: string; description: string }) => void }) {
  return (
    <div className="workspace-stage relative flex h-full flex-col items-center justify-center gap-5 overflow-hidden px-6 text-center">
      <span className="orb left-[12%] top-[16%] size-64 bg-primary/20 animate-orb-drift" />
      <span className="orb bottom-[10%] right-[8%] size-72 bg-orange-400/15 animate-orb-drift [animation-delay:2s]" />

      <span className="rise-stagger stagger-1 relative flex size-16 items-center justify-center rounded-3xl bg-primary/15 text-primary glow-soft animate-float">
        <Sparkles className="size-8" />
      </span>
      <div className="relative max-w-md space-y-2.5">
        <h1 className="rise-stagger stagger-2 text-2xl font-semibold tracking-tight sm:text-3xl">
          Welcome to <span className="text-gradient">Rawal AI</span>
        </h1>
        <p className="rise-stagger stagger-3 text-sm leading-relaxed text-muted-foreground">
          Create a project to get a workspace. Each chat inside it runs in its own Linux sandbox,
          where the agent can write code, run commands, start servers and ship.
        </p>
      </div>
      <div className="rise-stagger stagger-4 relative flex flex-wrap items-center justify-center gap-2">
        {FIRST_RUN_PILLS.map((pill) => (
          <span
            key={pill.label}
            className="inline-flex items-center gap-1.5 rounded-full border border-border bg-surface/80 px-3 py-1.5 text-[12px] text-muted-foreground backdrop-blur"
          >
            <pill.icon className="size-3.5 text-primary" />
            {pill.label}
          </span>
        ))}
      </div>
      <div className="rise-stagger stagger-5 relative grid w-full max-w-3xl gap-3 sm:grid-cols-3">
        {QUICK_STARTS.map((item) => (
          <button key={item.title} type="button" onClick={() => onNewProject({ name: item.name, description: item.prompt })} className="lift gradient-border rounded-2xl p-4 text-left transition-colors hover:bg-primary/5">
            <span className="mb-3 flex size-9 items-center justify-center rounded-xl bg-primary/10 text-primary"><item.icon className="size-4" /></span>
            <span className="block text-sm font-semibold">{item.title}</span>
            <span className="mt-1 block text-xs leading-relaxed text-muted-foreground">{item.description}</span>
          </button>
        ))}
      </div>
      <Button onClick={() => onNewProject()} size="lg" variant="outline" className="relative">
        <FolderPlus className="size-4" />
        Start from scratch
      </Button>
    </div>
  );
}

export function DesktopWorkspace() {
  const ready = useStore((s) => s.ready);
  const projects = useStore((s) => s.projects);
  const threads = useStore((s) => s.threads);
  const activeProjectId = useStore((s) => s.activeProjectId);
  const activeThreadId = useStore((s) => s.activeThreadId);
  const createThread = useStore((s) => s.createThread);
  const computerOpen = useStore((s) => s.computerOpen);
  const callActive = useStore((s) => s.callActive);
  const setCallActive = useStore((s) => s.setCallActive);

  const [settingsOpen, setSettingsOpen] = useState(false);
  const [projectOpen, setProjectOpen] = useState(false);
  const [projectTemplate, setProjectTemplate] = useState<{ name: string; description: string } | undefined>();
  const [shortcutsOpen, setShortcutsOpen] = useState(false);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const keymap = useStore((s) => s.keymap);
  const [sidebarOpen, setSidebarOpen] = useState(
    () => typeof window !== "undefined" && localStorage.getItem("bhati.sidebar") !== "closed",
  );

  const voice = useVoiceAssistant();
  useEventStream(activeThreadId);

  useEffect(() => {
    localStorage.setItem("bhati.sidebar", sidebarOpen ? "open" : "closed");
  }, [sidebarOpen]);

  useEffect(() => {
    if (ready && activeProjectId && threads.length === 0) void createThread(activeProjectId);
  }, [ready, activeProjectId, threads.length, createThread]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const key = event.key.toLowerCase();
      if ((event.metaKey || event.ctrlKey) && key === "k") {
        event.preventDefault();
        setPaletteOpen((v) => !v);
        return;
      }
      if ((event.metaKey || event.ctrlKey) && key === keymap.sidebar) {
        event.preventDefault();
        setSidebarOpen((v) => !v);
      }
      if ((event.metaKey || event.ctrlKey) && event.key === keymap.settings) {
        event.preventDefault();
        setSettingsOpen(true);
      }
      if ((event.metaKey || event.ctrlKey) && key === keymap.newChat && activeProjectId) {
        event.preventDefault();
        void createThread(activeProjectId);
      }
      if (event.key === "?" && document.activeElement?.tagName !== "INPUT" && document.activeElement?.tagName !== "TEXTAREA") {
        event.preventDefault();
        setShortcutsOpen((v) => !v);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [activeProjectId, createThread, keymap]);

  const openNewProject = (template?: { name: string; description: string }) => {
    setProjectTemplate(template);
    setProjectOpen(true);
  };

  return (
    <div className="workspace-stage flex h-full overflow-hidden bg-background">
      {/* Sidebar */}
      <div
        className={cn(
          "shrink-0 transition-[margin,transform] duration-200 z-40",
          sidebarOpen
            ? "static w-[264px]"
            : "static w-[264px] -ml-[264px] translate-x-0",
        )}
      >
        <Sidebar
          onOpenSettings={() => setSettingsOpen(true)}
            onNewProject={() => openNewProject()}
        />
      </div>

      <div className="flex min-w-0 flex-1 flex-col">
        <div className="relative">
          <Button
            variant="ghost"
            size="icon-sm"
            onClick={() => setSidebarOpen((v) => !v)}
            className="absolute left-2 top-2 z-10"
            title="Toggle sidebar (⌘B)"
            aria-label={sidebarOpen ? "Close sidebar" : "Open sidebar"}
            aria-expanded={sidebarOpen}
          >
            {sidebarOpen ? <PanelLeftClose className="size-4" /> : <PanelLeftOpen className="size-4" />}
          </Button>
          <div className="pl-10">
            <TopBar />
          </div>
        </div>

        {projects.length === 0 ? (
          <FirstRun onNewProject={openNewProject} />
        ) : (
          <SplitPane left={<ChatPanel />} right={<ComputerPanel />} showRight={computerOpen} />
        )}
      </div>

      {callActive && <CallMode voice={voice} onClose={() => setCallActive(false)} />}
      <SettingsDialog open={settingsOpen} onOpenChange={setSettingsOpen} />
      <NewProjectDialog
        open={projectOpen}
        onOpenChange={(open) => {
          setProjectOpen(open);
          if (!open) setProjectTemplate(undefined);
        }}
        initialName={projectTemplate?.name}
        initialDescription={projectTemplate?.description}
      />
      <ShortcutsDialog open={shortcutsOpen} onOpenChange={setShortcutsOpen} />
      <CommandPalette open={paletteOpen} onOpenChange={setPaletteOpen} onOpenSettings={() => setSettingsOpen(true)} />
    </div>
  );
}
