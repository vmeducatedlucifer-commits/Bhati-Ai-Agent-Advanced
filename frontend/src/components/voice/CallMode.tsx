import { Hammer, MessageCircle, Mic, MicOff, PhoneOff, Scissors, TriangleAlert } from "lucide-react";
import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { Button } from "@/components/ui/button";
import { useVoiceAssistant } from "@/hooks/useVoiceAssistant";
import { useStore } from "@/lib/store";
import { cn } from "@/lib/utils";
import { voiceErrorMessage } from "@/components/voice/VoiceAssistant";

function formatTimer(total: number): string {
  const m = Math.floor(total / 60).toString().padStart(2, "0");
  const s = (total % 60).toString().padStart(2, "0");
  return `${m}:${s}`;
}

/**
 * Full-screen phone-call style live conversation overlay.
 *
 * Rendered via portal straight into document.body: ancestors up the tree use
 * backdrop-blur / transforms, which would otherwise turn `fixed inset-0`
 * into a box relative to a small parent and push the UI off-screen.
 */
export function CallMode({
  voice,
  onClose,
}: {
  voice: ReturnType<typeof useVoiceAssistant>;
  onClose: () => void;
}) {
  const setCallActive = useStore((s) => s.setCallActive);
  const messages = useStore((s) => s.messages);
  const running = useStore((s) => s.running);
  const thread = useStore((s) => s.threads.find((t) => t.id === s.activeThreadId));
  const setThreadMode = useStore((s) => s.setThreadMode);
  const [seconds, setSeconds] = useState(0);
  const [muted, setMuted] = useState(false);

  const { state, interim, transcript, startListening, stopListening, pauseListening, interruptSpeech } = voice;
  const listening = state === "listening" && !muted;
  const speaking = state === "speaking";
  const mode = thread?.mode ?? "agent";

  const toggleMute = () => {
    if (muted) {
      setMuted(false);
      startListening();
    } else {
      setMuted(true);
      pauseListening();
    }
  };

  useEffect(() => {
    setCallActive(true);
    startListening();
    const timer = window.setInterval(() => setSeconds((s) => s + 1), 1000);
    // Freeze the page behind the call.
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      window.clearInterval(timer);
      document.body.style.overflow = prevOverflow;
      setCallActive(false);
      stopListening();
      if ("speechSynthesis" in window) window.speechSynthesis.cancel();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const recent = messages.filter((m) => m.role !== "tool").slice(-4);
  const problem = voiceErrorMessage(voice);

  return createPortal(
    <div className="fixed inset-0 z-[100] overflow-y-auto overscroll-contain bg-background/95 backdrop-blur-xl animate-scale-in">
      <div className="mx-auto flex min-h-dvh w-full max-w-lg flex-col items-center px-6 pb-[max(1.5rem,env(safe-area-inset-bottom))] pt-8 sm:pt-10">
        {/* ambient orbs */}
        <span className="orb left-1/2 top-[6%] size-72 -translate-x-1/2 bg-primary/20 animate-orb-drift" />
        <span className="orb bottom-[2%] left-[8%] size-56 bg-purple-500/15 animate-orb-drift [animation-delay:3s]" />

        <div className="relative flex shrink-0 flex-col items-center gap-1.5 text-center">
          <p className="text-[12px] font-medium uppercase tracking-widest text-muted-foreground">
            Live call · {formatTimer(seconds)}
          </p>
          <h2 className="max-w-xs truncate text-xl font-semibold tracking-tight">{thread?.title ?? "Agent call"}</h2>
          <p className={cn("text-[13px]", listening ? "text-emerald-500" : speaking ? "text-purple-400" : problem ? "text-danger" : muted ? "text-warning" : "text-muted-foreground")}>
            {problem && !listening && !speaking ? problem.title : muted ? "Muted" : listening ? "Listening…" : speaking ? "Speaking…" : running ? "Thinking…" : "Connecting…"}
          </p>
        </div>

        {/* Agent / Chat mode for this call */}
        <div className="relative mt-3 flex items-center gap-1 rounded-full border border-border bg-surface/80 p-1 backdrop-blur">
          {(
            [
              ["agent", "Agent", Hammer, "Full tools — builds, edits, runs"],
              ["chat", "Chat", MessageCircle, "Conversation only, no tools"],
            ] as const
          ).map(([value, label, Icon, hint]) => (
            <button
              key={value}
              type="button"
              title={hint}
              disabled={running}
              onClick={() => void setThreadMode(value)}
              className={cn(
                "flex items-center gap-1.5 rounded-full px-3.5 py-1.5 text-[12.5px] font-medium transition-all disabled:opacity-50",
                mode === value ? "bg-primary text-primary-foreground shadow" : "text-muted-foreground hover:text-foreground",
              )}
            >
              <Icon className="size-3.5" />
              {label}
            </button>
          ))}
        </div>

        {/* avatar orb */}
        <div className="relative my-6 flex size-36 shrink-0 items-center justify-center sm:my-8 sm:size-44">
          {listening && (
            <>
              <span className="absolute inset-0 rounded-full border-2 border-primary/50 animate-pulse-ring" />
              <span className="absolute inset-0 rounded-full border border-emerald-400/40 animate-pulse-ring [animation-delay:700ms]" />
            </>
          )}
          {speaking && <span className="absolute inset-0 rounded-full border-2 border-purple-400/50 animate-pulse-ring" />}
          <span className={cn(
            "flex size-24 items-center justify-center rounded-full text-3xl font-semibold shadow-2xl transition-colors sm:size-28",
            listening ? "bg-primary text-primary-foreground shadow-primary/40" : "bg-muted text-muted-foreground",
          )}>
            R
          </span>
          {(listening || speaking) && (
            <div className="absolute -bottom-2 flex h-6 items-center gap-[3px]">
              <span className="eq-bar h-4" />
              <span className="eq-bar h-6 [animation-delay:120ms]" />
              <span className="eq-bar h-3 [animation-delay:240ms]" />
              <span className="eq-bar h-5 [animation-delay:360ms]" />
              <span className="eq-bar h-4 [animation-delay:480ms]" />
            </div>
          )}
        </div>

        {/* live transcript / problem */}
        <div className="relative min-h-12 w-full shrink-0 text-center">
          {problem ? (
            <div className="mx-auto max-w-sm rounded-2xl border border-danger/40 bg-danger/5 p-3 animate-message-in">
              <p className="flex items-center justify-center gap-1.5 text-[13px] font-semibold text-danger">
                <TriangleAlert className="size-4" />
                {problem.title}
              </p>
              <p className="mt-1 text-[12px] text-muted-foreground">{problem.hint}</p>
            </div>
          ) : (
            <p className="truncate font-mono text-[13px] text-foreground">
              {interim || transcript || <span className="italic text-muted-foreground">Say anything…</span>}
            </p>
          )}
        </div>

        {/* recent exchange */}
        {recent.length > 0 ? (
          <div className="scrollbar-thin relative mt-2 max-h-32 w-full shrink-0 space-y-1.5 overflow-y-auto">
            {recent.map((m) => (
              <p key={m.id} className="truncate text-[12px] text-muted-foreground">
                <span className={cn("mr-1.5 font-semibold", m.role === "user" ? "text-sky-400" : "text-primary")}>
                  {m.role === "user" ? "You" : "Agent"}:
                </span>
                {m.content || "…"}
              </p>
            ))}
          </div>
        ) : null}

        {/* controls — pinned at the bottom of the visible call sheet */}
        <div className="relative mt-auto flex shrink-0 items-center gap-4 pt-6">
          <div className="flex flex-col items-center gap-1">
            <Button
              size="icon"
              variant="outline"
              className="size-14 rounded-full"
              onClick={toggleMute}
            >
              {muted ? <MicOff className="size-5" /> : <Mic className="size-5" />}
            </Button>
            <span className="text-[11px] text-muted-foreground">{muted ? "Unmute" : "Mute"}</span>
          </div>
          {speaking ? (
            <div className="flex flex-col items-center gap-1 animate-scale-in">
              <Button
                size="icon"
                variant="secondary"
                className="size-14 rounded-full"
                onClick={() => interruptSpeech()}
              >
                <Scissors className="size-5" />
              </Button>
              <span className="text-[11px] text-muted-foreground">Interrupt</span>
            </div>
          ) : null}
          <div className="flex flex-col items-center gap-1">
            <Button size="icon" variant="danger" className="size-16 rounded-full shadow-xl" onClick={onClose}>
              <PhoneOff className="size-6" />
            </Button>
            <span className="text-[11px] text-muted-foreground">End</span>
          </div>
        </div>
      </div>
    </div>,
    document.body,
  );
}
