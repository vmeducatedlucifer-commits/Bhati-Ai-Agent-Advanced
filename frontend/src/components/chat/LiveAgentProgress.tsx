import { Brain, Square, Terminal, Wrench } from "lucide-react";
import { Button } from "@/components/ui/button";
import { hapticLight } from "@/lib/haptics";
import { useStore } from "@/lib/store";

export function LiveAgentProgress() {
  const running = useStore((s) => s.running);
  const activeProgress = useStore((s) => s.activeProgress);
  const runMeta = useStore((s) => s.runMeta);
  const interrupt = useStore((s) => s.interrupt);

  if (!running) return null;

  const isTool = activeProgress?.kind === "tool";
  const toolName = activeProgress?.name || "tool";
  const elapsed = activeProgress?.elapsed_s ? `${activeProgress.elapsed_s.toFixed(1)}s` : "";
  const isLongRunning = (activeProgress?.elapsed_s || 0) > 20;

  const handleInterrupt = () => {
    hapticLight();
    void interrupt();
  };

  return (
    <div className="mx-3 my-2 flex items-center justify-between gap-3 rounded-xl border border-primary/30 bg-primary/5 px-3.5 py-2.5 shadow-xs backdrop-blur-md animate-message-in">
      <div className="flex min-w-0 items-center gap-2.5">
        {/* Animated Icon Indicator */}
        <div className="relative flex size-7 shrink-0 items-center justify-center rounded-lg bg-primary/15 text-primary">
          {isTool ? (
            toolName === "bash" ? (
              <Terminal className="size-4 animate-pulse text-emerald-400" />
            ) : (
              <Wrench className="size-4 animate-spin-slow text-primary" />
            )
          ) : (
            <Brain className="size-4 animate-pulse text-primary" />
          )}
          <span className="absolute -right-0.5 -top-0.5 size-2 rounded-full bg-primary animate-ping" />
        </div>

        {/* Text & Status */}
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5">
            <span className="text-xs font-bold text-foreground">
              {isTool ? `Executing: ${toolName}` : "AI is Thinking & Generating"}
            </span>
            {elapsed && (
              <span className="font-mono text-[11px] font-semibold text-primary">
                ({elapsed})
              </span>
            )}
          </div>
          <p className="truncate text-[10.5px] text-muted-foreground">
            {isLongRunning
              ? "Running long task — stream watchdog is active, keeping alive..."
              : isTool
              ? `Processing sandbox ${toolName} execution`
              : `Model: ${runMeta?.model || "active model"} • streaming response`}
          </p>
        </div>
      </div>

      {/* Stop / Cancel Button */}
      <Button
        variant="outline"
        size="xs"
        onClick={handleInterrupt}
        className="h-7 gap-1 px-2 text-xs border-danger/40 text-danger hover:bg-danger/10 hover:border-danger shrink-0 rounded-lg"
        title="Stop and interrupt current turn"
      >
        <Square className="size-3 fill-danger" />
        <span>Stop</span>
      </Button>
    </div>
  );
}
