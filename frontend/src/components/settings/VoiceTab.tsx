import { Check, Languages, Mic, Play, Plus, Trash2, Zap } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useVoiceAssistant } from "@/hooks/useVoiceAssistant";
import { useStore } from "@/lib/store";
import { DEFAULT_SHORTCUTS, loadShortcuts, saveShortcuts, type VoiceShortcut } from "@/lib/voiceShortcuts";

const LANGUAGES = [
  { label: "Hindi (India) - हिंदी", code: "hi-IN" },
  { label: "English (India)", code: "en-IN" },
  { label: "English (United States)", code: "en-US" },
  { label: "English (United Kingdom)", code: "en-GB" },
];

export function VoiceTab() {
  const voiceEnabled = useStore((s) => s.voiceEnabled);
  const voiceMode = useStore((s) => s.voiceMode);
  const voiceTrigger = useStore((s) => s.voiceTrigger);
  const voiceRate = useStore((s) => s.voiceRate);
  const voicePitch = useStore((s) => s.voicePitch);
  const wakeEnabled = useStore((s) => s.wakeEnabled);
  const setWakeEnabled = useStore((s) => s.setWakeEnabled);
  const translateMode = useStore((s) => s.translateMode);
  const translateTarget = useStore((s) => s.translateTarget);
  const setVoiceSettings = useStore((s) => s.setVoiceSettings);

  const voice = useVoiceAssistant({});
  const { availableVoices, selectedVoice, setSelectedVoice, voiceLang, setVoiceLang, speak } = voice;

  const [triggerInput, setTriggerInput] = useState(voiceTrigger);
  const [shortcuts, setShortcuts] = useState<VoiceShortcut[]>(() => loadShortcuts());
  const [phrase, setPhrase] = useState("");
  const [action, setAction] = useState("");

  const supportProblem =
    !voice.supported || !voice.secureContext
      ? {
          title: !voice.supported ? "Voice input unavailable in this browser" : "Voice needs HTTPS or localhost",
          hint: !voice.supported
            ? "Use Chrome or Edge for speech recognition. Text-to-speech still works here."
            : "You are on plain HTTP — recognition is blocked. Use HTTPS or localhost.",
        }
      : null;

  const updateShortcuts = (list: VoiceShortcut[]) => {
    setShortcuts(list);
    saveShortcuts(list);
  };

  const filteredVoices = availableVoices.filter(
    (v) => v.lang.includes(voiceLang) || v.lang.startsWith(voiceLang.split("-")[0])
  );

  return (
    <div className="space-y-6">
      <div>
        <h3 className="text-sm font-semibold tracking-tight">Gemini Live-like Voice Assistant</h3>
        <p className="text-[12.5px] text-muted-foreground">
          Talk to Rawal AI using natural speech (Hindi & English). Free, browser-native Web Speech API — no API key required.
        </p>
      </div>

      {supportProblem ? (
        <div className="rounded-xl border border-warning/40 bg-warning/5 p-3">
          <p className="text-[13px] font-medium text-warning">{supportProblem.title}</p>
          <p className="text-[12px] text-muted-foreground">{supportProblem.hint}</p>
        </div>
      ) : null}

      {/* Enable Toggle */}
      <div className="flex items-center justify-between rounded-xl border border-border bg-surface p-3.5">
        <div className="flex items-center gap-3">
          <div className="flex size-9 items-center justify-center rounded-lg bg-primary/10 text-primary">
            <Mic className="size-5" />
          </div>
          <div>
            <p className="text-[13.5px] font-medium">Enable Voice Assistant</p>
            <p className="text-[11.5px] text-muted-foreground">
              Listen to your voice commands & read agent replies out loud.
            </p>
          </div>
        </div>
        <Button
          variant={voiceEnabled ? "default" : "outline"}
          size="sm"
          onClick={() => setVoiceSettings({ voiceEnabled: !voiceEnabled })}
        >
          {voiceEnabled ? "Enabled" : "Disabled"}
        </Button>
      </div>

      {/* Language Selection */}
      <div className="space-y-2">
        <label className="text-[12.5px] font-medium">Language Accent</label>
        <div className="grid grid-cols-2 gap-2">
          {LANGUAGES.map((lang) => (
            <button
              key={lang.code}
              type="button"
              onClick={() => setVoiceLang(lang.code)}
              className={`flex items-center justify-between rounded-lg border px-3 py-2 text-left text-xs transition-colors ${
                voiceLang === lang.code ? "border-primary bg-primary/10 font-medium text-primary" : "border-border bg-surface"
              }`}
            >
              <span>{lang.label}</span>
              {voiceLang === lang.code && <Check className="size-3.5" />}
            </button>
          ))}
        </div>
      </div>

      {/* Voice Model Selection */}
      <div className="space-y-2">
        <label className="text-[12.5px] font-medium">Text-to-Speech Voice</label>
        <div className="flex gap-2">
          <select
            value={selectedVoice?.name || ""}
            onChange={(e) => {
              const found = availableVoices.find((v) => v.name === e.target.value);
              if (found) setSelectedVoice(found);
            }}
            className="h-9 flex-1 rounded-lg border border-border bg-surface px-3 text-xs text-foreground focus:outline-none"
          >
            {filteredVoices.length === 0 ? (
              <option value="">Default System Voice</option>
            ) : (
              filteredVoices.map((v) => (
                <option key={v.name} value={v.name}>
                  {v.name} ({v.lang})
                </option>
              ))
            )}
          </select>

          <Button
            variant="outline"
            size="sm"
            onClick={() => speak(voiceLang.startsWith("hi") ? "नमस्ते, मैं रावल एजेंट हूँ। मैं आपकी क्या मदद कर सकता हूँ?" : "Hello, I am Rawal AI. How can I help you today?")}
          >
            <Play className="size-3.5" />
            Test Voice
          </Button>
        </div>
      </div>

      {/* Sending Modes */}
      <div className="space-y-2.5">
        <label className="text-[12.5px] font-medium">Voice Interaction Mode</label>

        <div className="grid gap-2">
          {/* Mode 1: Type Only */}
          <button
            type="button"
            onClick={() => setVoiceSettings({ voiceMode: "type" })}
            className={`flex items-start gap-3 rounded-xl border p-3 text-left transition-colors ${
              voiceMode === "type" ? "border-primary bg-primary/10" : "border-border bg-surface"
            }`}
          >
            <div className="mt-0.5 font-mono text-xs font-semibold text-primary">01</div>
            <div>
              <p className="text-xs font-medium">Type Only (Review Before Send)</p>
              <p className="text-[11px] text-muted-foreground">
                Transcribes your voice into the chat input. Leaves text in the box for you to review and click Send.
              </p>
            </div>
          </button>

          {/* Mode 2: Auto Send */}
          <button
            type="button"
            onClick={() => setVoiceSettings({ voiceMode: "send" })}
            className={`flex items-start gap-3 rounded-xl border p-3 text-left transition-colors ${
              voiceMode === "send" ? "border-primary bg-primary/10" : "border-border bg-surface"
            }`}
          >
            <div className="mt-0.5 font-mono text-xs font-semibold text-primary">02</div>
            <div>
              <p className="text-xs font-medium">Gemini Live Auto-Send (Continuous Dialogue)</p>
              <p className="text-[11px] text-muted-foreground">
                Automatically sends your prompt as soon as you finish speaking, and speaks the AI response back to you.
              </p>
            </div>
          </button>

          {/* Mode 3: Confirmation Code */}
          <button
            type="button"
            onClick={() => setVoiceSettings({ voiceMode: "confirm" })}
            className={`flex items-start gap-3 rounded-xl border p-3 text-left transition-colors ${
              voiceMode === "confirm" ? "border-primary bg-primary/10" : "border-border bg-surface"
            }`}
          >
            <div className="mt-0.5 font-mono text-xs font-semibold text-primary">03</div>
            <div>
              <p className="text-xs font-medium">Confirmation Keyword Trigger</p>
              <p className="text-[11px] text-muted-foreground">
                Transcribes your speech and ONLY sends when you speak your specific secret confirmation code/phrase.
              </p>
            </div>
          </button>
        </div>
      </div>

      {/* Confirmation Keyword Input */}
      {voiceMode === "confirm" && (
        <div className="space-y-2 rounded-xl border border-primary/30 bg-primary/5 p-3">
          <label className="text-[12px] font-medium text-primary">Secret Confirmation Phrase / Code</label>
          <div className="flex gap-2">
            <Input
              value={triggerInput}
              onChange={(e) => setTriggerInput(e.target.value)}
              placeholder="e.g. send now, haan bhej do, confirm"
              className="h-8 text-xs"
            />
            <Button
              size="sm"
              onClick={() => setVoiceSettings({ voiceTrigger: triggerInput.trim() || "send now" })}
            >
              Save Phrase
            </Button>
          </div>
        </div>
      )}

      {/* Voice tuning */}
      <div className="space-y-3 rounded-xl border border-border bg-surface p-3.5">
        <p className="text-[12.5px] font-medium">Voice tuning</p>
        <div>
          <div className="mb-1 flex justify-between text-[11.5px] text-muted-foreground">
            <span>Speaking speed</span>
            <span className="tabular-nums">{voiceRate.toFixed(2)}×</span>
          </div>
          <input
            type="range"
            min={0.5}
            max={2}
            step={0.05}
            value={voiceRate}
            onChange={(e) => setVoiceSettings({ voiceRate: Number(e.target.value) })}
            className="h-2 w-full cursor-pointer appearance-none rounded-full bg-muted"
          />
        </div>
        <div>
          <div className="mb-1 flex justify-between text-[11.5px] text-muted-foreground">
            <span>Pitch</span>
            <span className="tabular-nums">{voicePitch.toFixed(2)}</span>
          </div>
          <input
            type="range"
            min={0}
            max={2}
            step={0.05}
            value={voicePitch}
            onChange={(e) => setVoiceSettings({ voicePitch: Number(e.target.value) })}
            className="h-2 w-full cursor-pointer appearance-none rounded-full bg-muted"
          />
        </div>
        <div className="flex items-center justify-between pt-1">
          <div>
            <p className="text-[12.5px] font-medium">Wake word — “Hey Rawal”</p>
            <p className="text-[11px] text-muted-foreground">Hands-free: saying it starts listening. Chrome/Edge only.</p>
          </div>
          <Button
            variant={wakeEnabled ? "default" : "outline"}
            size="sm"
            onClick={() => setWakeEnabled(!wakeEnabled)}
          >
            {wakeEnabled ? "On" : "Off"}
          </Button>
        </div>
        <p className="text-[11px] text-muted-foreground">Tip: just start talking while it speaks to interrupt (barge-in).</p>
      </div>

      {/* Auto-translate */}
      <div className="space-y-2.5 rounded-xl border border-border bg-surface p-3.5">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Languages className="size-4 text-primary" />
            <div>
              <p className="text-[13px] font-medium">Auto-translate replies</p>
              <p className="text-[11px] text-muted-foreground">Hindi bolo → English jawab, ya ulta. Kisi bhi mode me.</p>
            </div>
          </div>
          <Button
            variant={translateMode ? "default" : "outline"}
            size="sm"
            onClick={() => setVoiceSettings({ translateMode: !translateMode })}
          >
            {translateMode ? "On" : "Off"}
          </Button>
        </div>
        <div className="grid grid-cols-2 gap-2">
          {(
            [
              ["en", "Hindi → English"],
              ["hi", "English → Hindi"],
            ] as const
          ).map(([target, label]) => (
            <button
              key={target}
              type="button"
              onClick={() => setVoiceSettings({ translateTarget: target, translateMode: true })}
              className={`rounded-lg border px-3 py-2 text-left text-xs transition-colors ${
                translateTarget === target
                  ? "border-primary bg-primary/10 font-medium text-primary"
                  : "border-border bg-surface"
              }`}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      {/* Voice shortcuts */}
      <div className="space-y-2.5 rounded-xl border border-border bg-surface p-3.5">
        <div className="flex items-center gap-2">
          <Zap className="size-4 text-primary" />
          <div>
            <p className="text-[13px] font-medium">Voice commands</p>
            <p className="text-[11px] text-muted-foreground">Ye phrase bolo → ye prompt chalega. Dono bhashaon me.</p>
          </div>
        </div>
        <ul className="space-y-1.5">
          {shortcuts.map((s) => (
            <li key={s.id} className="rounded-lg border border-border px-3 py-2">
              <div className="flex items-center gap-2">
                <p className="flex-1 font-mono text-[12px] text-primary">“{s.phrase}”</p>
                <button
                  type="button"
                  onClick={() => updateShortcuts(shortcuts.filter((x) => x.id !== s.id))}
                  className="rounded p-1 text-muted-foreground hover:text-danger"
                >
                  <Trash2 className="size-3.5" />
                </button>
              </div>
              <p className="mt-0.5 line-clamp-2 text-[11.5px] text-muted-foreground">{s.action}</p>
            </li>
          ))}
        </ul>
        <div className="space-y-2 rounded-lg border border-dashed border-border p-2.5">
          <Input value={phrase} onChange={(e) => setPhrase(e.target.value)} placeholder="Spoken phrase (e.g. deploy kar do)" className="h-8 text-xs" />
          <Input value={action} onChange={(e) => setAction(e.target.value)} placeholder="Agent prompt to run" className="h-8 text-xs" />
          <div className="flex gap-2">
            <Button
              size="sm"
              disabled={!phrase.trim() || !action.trim()}
              onClick={() => {
                updateShortcuts([...shortcuts, { id: `c-${Date.now()}`, phrase: phrase.trim(), action: action.trim() }]);
                setPhrase("");
                setAction("");
              }}
            >
              <Plus className="size-3.5" />
              Add command
            </Button>
            <Button size="sm" variant="ghost" onClick={() => updateShortcuts([...DEFAULT_SHORTCUTS])}>
              Reset defaults
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
