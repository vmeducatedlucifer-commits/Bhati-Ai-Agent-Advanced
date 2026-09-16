import { AlertTriangle, Mic, Sparkles, Volume2, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Tooltip } from "@/components/ui/primitives";
import { useVoiceAssistant, type VoiceState } from "@/hooks/useVoiceAssistant";
import { useStore } from "@/lib/store";
import { cn } from "@/lib/utils";

type Voice = ReturnType<typeof useVoiceAssistant>;

/** Human-readable explanation for a voice failure + how to fix it. */
export function voiceErrorMessage(voice: Pick<Voice, "supported" | "secureContext" | "voiceError">): {
  title: string;
  hint: string;
} | null {
  if (!voice.supported) {
    return {
      title: "Voice input not supported here",
      hint: "Open this app in Chrome or Edge — Firefox and Safari lack speech recognition.",
    };
  }
  if (!voice.secureContext) {
    return {
      title: "Voice needs a secure page",
      hint: "Speech recognition only works over HTTPS or localhost. Plain HTTP IPs are blocked by the browser.",
    };
  }
  switch (voice.voiceError) {
    case "blocked":
      return {
        title: "Microphone blocked",
        hint: "Allow mic permission in the browser address bar, then tap the mic again.",
      };
    case "network":
      return { title: "Speech service unreachable", hint: "Check your internet connection and retry." };
    case "error":
      return { title: "Voice error", hint: "Tap the mic to try again." };
    default:
      return null;
  }
}

export function VoiceAssistantOrb({
  state,
  onClick,
}: {
  state: VoiceState;
  onClick: () => void;
}) {
  const isListening = state === "listening";
  const isSpeaking = state === "speaking";

  return (
    <div className="relative flex items-center justify-center">
      {/* Expanding pulse rings */}
      {isListening && (
        <>
          <span className="absolute size-10 rounded-full border-2 border-primary/50 animate-pulse-ring" />
          <span className="absolute size-10 rounded-full border border-emerald-400/40 animate-pulse-ring [animation-delay:600ms]" />
          <span className="absolute size-8 rounded-full bg-emerald-500/20 animate-glow-pulse" />
        </>
      )}
      {isSpeaking && (
        <span className="absolute size-10 rounded-full border-2 border-purple-400/50 animate-pulse-ring" />
      )}

      <Button
        key={isListening ? "listening" : isSpeaking ? "speaking" : "idle"}
        variant={isListening ? "default" : isSpeaking ? "secondary" : "outline"}
        size="icon-sm"
        onClick={onClick}
        className={cn(
          "relative animate-scale-in transition-all duration-300",
          isListening && "border-primary bg-primary text-primary-foreground shadow-lg shadow-primary/30",
          isSpeaking && "border-purple-500 bg-purple-500/20 text-purple-400"
        )}
      >
        {isListening ? (
          <Mic className="size-4 animate-glow-pulse" />
        ) : isSpeaking ? (
          <Volume2 className="size-4 animate-glow-pulse" />
        ) : (
          <Mic className="size-4" />
        )}
      </Button>
    </div>
  );
}

export function VoiceAssistantBar({
  voice,
}: {
  voice: ReturnType<typeof useVoiceAssistant>;
}) {
  const { state, interim, transcript, toggleListening, clearVoiceError } = voice;
  const voiceMode = useStore((s) => s.voiceMode);
  const voiceTrigger = useStore((s) => s.voiceTrigger);

  const problem = voiceErrorMessage(voice);
  if (problem) {
    return (
      <div className="flex items-center gap-3 rounded-2xl border border-danger/40 bg-danger/5 px-4 py-2 text-xs shadow-sm animate-message-in">
        <AlertTriangle className="size-4 shrink-0 text-danger" />
        <div className="min-w-0 flex-1">
          <p className="font-semibold text-danger">{problem.title}</p>
          <p className="truncate text-muted-foreground">{problem.hint}</p>
        </div>
        <Tooltip content="Dismiss">
          <Button variant="ghost" size="icon-sm" onClick={clearVoiceError}>
            <X className="size-3.5" />
          </Button>
        </Tooltip>
      </div>
    );
  }

  if (state === "idle" && !interim && !transcript) return null;

  return (
    <div className="flex items-center gap-3 rounded-2xl border border-primary/30 bg-primary/5 px-4 py-2 text-xs shadow-sm animate-message-in">
      <div className="flex items-center gap-2">
        <Sparkles className={cn("size-4 text-primary", state === "listening" && "animate-spin-slow")} />
        <span className="font-semibold text-primary">
          {state === "listening" ? "Listening…" : state === "speaking" ? "Speaking…" : "Voice Mode"}
        </span>
      </div>

      <div className="min-w-0 flex-1 truncate font-mono text-[12px] text-foreground">
        {interim || transcript || (
          <span className="text-muted-foreground italic">
            {voiceMode === "confirm" ? `Speak "${voiceTrigger}" to send` : "Say anything…"}
          </span>
        )}
      </div>

      {/* Equalizer bars */}
      {state === "listening" && (
        <div className="flex h-4 items-center gap-[3px]" aria-hidden>
          <span className="eq-bar h-3" />
          <span className="eq-bar h-4 [animation-delay:120ms]" />
          <span className="eq-bar h-2.5 [animation-delay:240ms]" />
          <span className="eq-bar h-4 [animation-delay:360ms]" />
          <span className="eq-bar h-3 [animation-delay:480ms]" />
        </div>
      )}

      <Tooltip content="Stop voice">
        <Button variant="ghost" size="icon-sm" onClick={toggleListening}>
          <X className="size-3.5" />
        </Button>
      </Tooltip>
    </div>
  );
}
