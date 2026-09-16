import {
  ArrowUp,
  ClipboardList,
  FileSearch,
  Link2,
  Loader2,
  Sparkles,
  WandSparkles,
} from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useStore } from "@/lib/store";
import { cn } from "@/lib/utils";

const QUICK_ACTIONS = [
  {
    label: "Inspect page",
    icon: FileSearch,
    prompt: "Inspect the currently open browser page. Summarize its purpose, key sections, important links, and any visible forms or actions. If the page is not available, explain what I should open first.",
  },
  {
    label: "Extract links",
    icon: Link2,
    prompt: "From the currently open browser page, collect the useful links and return them as a concise table with link text, URL, and what each link is for.",
  },
  {
    label: "Make a brief",
    icon: ClipboardList,
    prompt: "Read the currently open browser page and create a concise decision brief with the main point, supporting details, risks, and recommended next step.",
  },
];

export function BrowserAutomationBar({ currentUrl }: { currentUrl: string }) {
  const send = useStore((s) => s.send);
  const running = useStore((s) => s.running);
  const threadId = useStore((s) => s.activeThreadId);
  const setComputerTab = useStore((s) => s.setComputerTab);
  const [command, setCommand] = useState("");
  const [expanded, setExpanded] = useState(false);

  const run = async (prompt: string) => {
    const text = prompt.trim();
    if (!text || !threadId || running) return;
    const context = currentUrl ? `\n\nCurrent browser URL: ${currentUrl}` : "";
    await send(
      `Use the browser/preview context available in this project. Work carefully and do not claim to have clicked, typed, or observed anything that you could not actually access.\n\nBrowser task: ${text}${context}`,
    );
    setCommand("");
    setComputerTab("activity");
  };

  return (
    <div className="border-b border-border bg-surface/95 px-2.5 py-2 backdrop-blur">
      <div className="mb-1.5 flex items-center justify-between gap-2">
        <div className="flex min-w-0 items-center gap-1.5">
          <span className="flex size-5 shrink-0 items-center justify-center rounded-md bg-primary/12 text-primary">
            <WandSparkles className="size-3" />
          </span>
          <span className="text-[11px] font-semibold">Agent actions</span>
          <span className="truncate text-[10px] text-muted-foreground">
            {currentUrl ? "Page context attached" : "Open a page to add context"}
          </span>
        </div>
        <button
          type="button"
          onClick={() => setExpanded((value) => !value)}
          className="text-[10px] font-medium text-primary hover:underline"
        >
          {expanded ? "Hide" : "Show all"}
        </button>
      </div>

      <div className="flex gap-1.5 overflow-x-auto pb-0.5">
        {QUICK_ACTIONS.map(({ label, icon: Icon, prompt }) => (
          <Button
            key={label}
            variant="outline"
            size="sm"
            disabled={!threadId || running}
            onClick={() => void run(prompt)}
            className="h-7 shrink-0 rounded-full px-2.5 text-[10.5px]"
          >
            <Icon className="size-3" />
            {label}
          </Button>
        ))}
      </div>

      {expanded ? (
        <div className="mt-2 rounded-xl border border-primary/20 bg-primary/[0.04] p-2">
          <div className="mb-1.5 flex items-center gap-1.5 text-[10px] text-muted-foreground">
            <Sparkles className="size-3 text-primary" />
            Describe what the agent should do with this page
          </div>
          <div className="flex items-center gap-1.5">
            <Input
              value={command}
              onChange={(event) => setCommand(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey) {
                  event.preventDefault();
                  void run(command);
                }
              }}
              placeholder="e.g. Find the pricing details and compare the plans"
              disabled={!threadId || running}
              className="h-8 rounded-lg bg-background text-[11px]"
            />
            <Button
              size="icon-sm"
              disabled={!command.trim() || !threadId || running}
              onClick={() => void run(command)}
              className={cn("size-8 shrink-0 rounded-lg", running && "animate-pulse")}
              title="Send browser task to agent"
            >
              {running ? <Loader2 className="size-3.5 animate-spin" /> : <ArrowUp className="size-3.5" />}
            </Button>
          </div>
          <p className="mt-1.5 text-[9.5px] leading-relaxed text-muted-foreground">
            The agent will use the available page context and tools, then show its work in Activity.
          </p>
        </div>
      ) : null}
    </div>
  );
}
