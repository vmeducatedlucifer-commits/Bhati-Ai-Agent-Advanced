import { useEffect, useRef, useState, useCallback } from "react";
import { useStore } from "@/lib/store";
import { wrapTranslate } from "@/lib/translate";
import { matchShortcut } from "@/lib/voiceShortcuts";

export type VoiceState = "idle" | "listening" | "processing" | "speaking";

function normalizeEcho(s: string): string {
  return s
    .toLowerCase()
    .replace(/[^a-z0-9\u0900-\u097f\s]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

/** True when the transcript is just the agent's own recent speech leaking in. */
function isSelfEcho(text: string, spoken: string, spokenAt: number): boolean {
  if (!spoken || Date.now() - spokenAt > 15000) return false;
  const a = normalizeEcho(text);
  const b = normalizeEcho(spoken);
  if (a.length < 10 || b.length < 10) return false;
  return b.includes(a) || a.includes(b);
}

export function useVoiceAssistant({
  onTranscript,
  onSend,
  enableWake = false,
}: {
  onTranscript?: (text: string) => void;
  onSend?: (text: string) => void;
  /** When true, this instance also runs the hands-free wake-word listener. */
  enableWake?: boolean;
} = {}) {
  const [state, setState] = useState<VoiceState>("idle");
  const [transcript, setTranscript] = useState("");
  const [interim, setInterim] = useState("");
  const [selectedVoice, setSelectedVoice] = useState<SpeechSynthesisVoice | null>(null);
  const [availableVoices, setAvailableVoices] = useState<SpeechSynthesisVoice[]>([]);
  const [wakeActive, setWakeActive] = useState(false);
  const [wakeNonce, setWakeNonce] = useState(0);
  const [voiceLang, setVoiceLang] = useState<string>(() => {
    if (typeof localStorage !== 'undefined') {
       return localStorage.getItem("rawal.voiceLang") || "hi-IN";
    }
    return "hi-IN";
  });

  const recognitionRef = useRef<any>(null);
  const wakeRef = useRef<any>(null);
  const isListeningRef = useRef(false);
  // Half-duplex discipline: the mic must never be open while TTS is playing,
  // or the agent hears itself and answers itself forever.
  const resumeTimerRef = useRef<number | null>(null);
  const suppressResumeRef = useRef(false);
  const mutedRef = useRef(false);
  const lastSpokenRef = useRef<{ text: string; at: number }>({ text: "", at: 0 });

  // Callbacks arrive as fresh inline functions every render — mirror them in
  // refs so the recognition effect below never re-runs (re-running kills the
  // mic mid-speech). Modes are read via getState() inside handlers instead.
  const onTranscriptRef = useRef(onTranscript);
  const onSendRef = useRef(onSend);
  useEffect(() => {
    onTranscriptRef.current = onTranscript;
    onSendRef.current = onSend;
  });

  // Support / error surfacing (never fail silently).
  const [voiceError, setVoiceError] = useState<string | null>(null);
  const supported =
    typeof window !== "undefined" &&
    !!((window as unknown as Record<string, unknown>).SpeechRecognition ||
      (window as unknown as Record<string, unknown>).webkitSpeechRecognition);
  const secureContext = typeof window !== "undefined" && window.isSecureContext;
  const ttsSupported = typeof window !== "undefined" && "speechSynthesis" in window;

  const voiceEnabled = useStore((s) => s.voiceEnabled);
  const voiceRate = useStore((s) => s.voiceRate);
  const voicePitch = useStore((s) => s.voicePitch);
  const wakeEnabled = useStore((s) => s.wakeEnabled);
  const messages = useStore((s) => s.messages);

  const lastSpokenMsgId = useRef<string | null>(null);

  // Initialize Speech Synthesis Voices
  useEffect(() => {
    if (typeof window === "undefined" || !("speechSynthesis" in window)) return;

    const updateVoices = () => {
      const voices = window.speechSynthesis.getVoices();
      setAvailableVoices(voices);

      // Prioritize natural / neural voices for Hindi / English India / English US
      const preferred =
        voices.find((v) => v.lang.includes(voiceLang) && (v.name.includes("Natural") || v.name.includes("Google") || v.name.includes("Neural"))) ||
        voices.find((v) => v.lang.includes(voiceLang)) ||
        voices.find((v) => v.lang.startsWith("hi")) ||
        voices.find((v) => v.lang.startsWith("en")) ||
        voices[0];

      if (preferred) setSelectedVoice(preferred);
    };

    updateVoices();
    window.speechSynthesis.onvoiceschanged = updateVoices;
    return () => {
      window.speechSynthesis.onvoiceschanged = null;
    };
  }, [voiceLang]);

  const stopWake = useCallback(() => {
    if (wakeRef.current) {
      try {
        wakeRef.current.stop();
      } catch (e) {}
      wakeRef.current = null;
    }
    setWakeActive(false);
  }, []);

  const clearResumeTimer = () => {
    if (resumeTimerRef.current !== null) {
      window.clearTimeout(resumeTimerRef.current);
      resumeTimerRef.current = null;
    }
  };

  const startListening = useCallback(async () => {
    if (!supported) {
      setVoiceError("unsupported");
      return;
    }
    // Explicitly request microphone permission via getUserMedia if available
    if (typeof navigator !== "undefined" && navigator.mediaDevices?.getUserMedia) {
      try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        stream.getTracks().forEach((track) => track.stop());
      } catch (err: any) {
        console.warn("Microphone permission denied:", err);
        setVoiceError("blocked");
        return;
      }
    }
    if (recognitionRef.current && !isListeningRef.current) {
      try {
        setVoiceError(null);
        mutedRef.current = false;
        suppressResumeRef.current = false;
        clearResumeTimer();
        stopWake(); // main mic takes over from the wake listener
        if ("speechSynthesis" in window) window.speechSynthesis.cancel();
        recognitionRef.current.start();
      } catch (e) {
        console.warn("Error starting speech recognition:", e);
      }
    }
  }, [stopWake, supported]);

  const stopListening = useCallback(() => {
    // Full stop: mic + speech + no auto-resume.
    suppressResumeRef.current = true;
    mutedRef.current = false;
    clearResumeTimer();
    if (recognitionRef.current) {
      isListeningRef.current = false;
      try {
        recognitionRef.current.stop();
      } catch (e) {}
    }
    if ("speechSynthesis" in window) {
      window.speechSynthesis.cancel();
    }
    setState("idle");
  }, []);

  const pauseListening = useCallback(() => {
    // Mute: close the mic but let speech finish; TTS-end must not reopen it.
    mutedRef.current = true;
    suppressResumeRef.current = true;
    clearResumeTimer();
    isListeningRef.current = false;
    try {
      recognitionRef.current?.stop();
    } catch (e) {}
    setState((prev) => (prev === "listening" ? "idle" : prev));
  }, []);

  const scheduleResume = useCallback(
    (delay = 500) => {
      clearResumeTimer();
      resumeTimerRef.current = window.setTimeout(() => {
        resumeTimerRef.current = null;
        if (suppressResumeRef.current || mutedRef.current) return;
        const st = useStore.getState();
        if (voiceEnabled || st.callActive) startListening();
      }, delay);
    },
    [voiceEnabled, startListening],
  );

  const interruptSpeech = useCallback(() => {
    // Cut the agent's speech and hand the mic back (deterministic barge-in).
    suppressResumeRef.current = false;
    clearResumeTimer();
    if ("speechSynthesis" in window) window.speechSynthesis.cancel();
    setState("idle");
    const st = useStore.getState();
    if (st.callActive || voiceEnabled) scheduleResume(300);
  }, [voiceEnabled, scheduleResume]);

  const toggleListening = useCallback(() => {
    if (state === "listening" || state === "speaking") {
      stopListening();
    } else {
      startListening();
    }
  }, [state, startListening, stopListening]);

  // Speak text using SpeechSynthesis
  const speak = useCallback(
    (text: string) => {
      if (typeof window === "undefined" || !("speechSynthesis" in window) || !text) return;
      window.speechSynthesis.cancel(); // Stop any previous speech

      // Clean up text (strip markdown symbols like *, `, #)
      const cleanText = text
        .replace(/```[\s\S]*?```/g, " [code block omitted] ")
        .replace(/`([^`]+)`/g, "$1")
        .replace(/[*#_~]/g, "")
        .trim();

      if (!cleanText) return;
      lastSpokenRef.current = { text: cleanText.slice(0, 600), at: Date.now() };
      suppressResumeRef.current = false;

      const utterance = new SpeechSynthesisUtterance(cleanText);
      if (selectedVoice) utterance.voice = selectedVoice;
      utterance.rate = Math.min(2, Math.max(0.5, voiceRate || 1));
      utterance.pitch = Math.min(2, Math.max(0, voicePitch ?? 1));

      utterance.onstart = () => {
        // Half-duplex: close the mic the moment speech starts so the
        // recognizer can never hear the agent's own voice.
        isListeningRef.current = false;
        clearResumeTimer();
        try {
          recognitionRef.current?.stop();
        } catch (e) {}
        setState("speaking");
      };
      utterance.onend = () => {
        setState("idle");
        // Reopen after a short pause so the speaker tail decays first.
        scheduleResume(500);
      };
      utterance.onerror = () => {
        setState("idle");
        scheduleResume(500);
      };

      window.speechSynthesis.speak(utterance);
    },
    [selectedVoice, voiceRate, voicePitch, scheduleResume]
  );

  // Auto-speak new assistant messages if voice is enabled (or a live call is on)
  useEffect(() => {
    const st = useStore.getState();
    if (!voiceEnabled && !st.callActive) return;
    const lastMsg = messages[messages.length - 1];
    if (lastMsg && lastMsg.role === "assistant" && !lastMsg.streaming && lastMsg.content && lastMsg.id !== lastSpokenMsgId.current && !lastMsg.error) {
      lastSpokenMsgId.current = lastMsg.id;
      speak(lastMsg.content);
    }
  }, [messages, voiceEnabled, speak]);

  // Initialize Speech Recognition.
  // NOTE: deps are intentionally minimal. Callbacks live in refs and modes are
  // read via getState() — re-creating this effect mid-speech kills the mic.
  useEffect(() => {
    if (typeof window === "undefined") return;
    const SpeechRecognition = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
    if (!SpeechRecognition) {
      setVoiceError("unsupported");
      return;
    }

    // Stop any existing recognition instance
    if (recognitionRef.current) {
      try {
        recognitionRef.current.stop();
      } catch (e) {
        // ignore
      }
    }

    const recognition = new SpeechRecognition();
    recognition.continuous = true;
    recognition.interimResults = true;
    recognition.lang = voiceLang;

    recognition.onresult = (event: any) => {
      let currentInterim = "";
      let finalStr = "";

      for (let i = event.resultIndex; i < event.results.length; i++) {
        const result = event.results[i];
        if (result.isFinal) {
          finalStr += result[0].transcript + " ";
        } else {
          currentInterim += result[0].transcript;
        }
      }

      // No mic-driven barge-in here on purpose: cutting TTS on any interim
      // result is exactly how the agent ends up hearing itself. Interruption
      // is explicit via interruptSpeech() (call overlay / mic toggle).

      if (currentInterim) setInterim(currentInterim);

      if (finalStr) {
        const text = finalStr.trim();
        // Belt-and-braces echo guard: if the transcript is essentially what
        // TTS just said (speaker leaked into the mic), drop it silently.
        const last = lastSpokenRef.current;
        if (isSelfEcho(text, last.text, last.at)) {
          setInterim("");
          return;
        }
        setTranscript(text);
        setInterim("");
        onTranscriptRef.current?.(text);

        const st = useStore.getState();

        // Custom voice commands fire in every mode (including live calls).
        const shortcutAction = matchShortcut(text);
        if (shortcutAction) {
          onSendRef.current?.(shortcutAction);
          return;
        }

        // Check Modes (a live call always auto-sends like "send" mode)
        const wrapped = wrapTranslate(text, st.translateMode, st.translateTarget);
        if (st.voiceMode === "send" || st.callActive) {
          onSendRef.current?.(wrapped);
        } else if (st.voiceMode === "confirm") {
          const trigger = (st.voiceTrigger || "send now").toLowerCase();
          if (text.toLowerCase().includes(trigger)) {
            // Escape trigger pattern safely
            const escapedTrigger = trigger.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
            const cleanMessage = text.replace(new RegExp(escapedTrigger, "gi"), "").trim();
            if (cleanMessage) onSendRef.current?.(wrapTranslate(cleanMessage, st.translateMode, st.translateTarget));
          }
        }
      }
    };

    recognition.onstart = () => {
      isListeningRef.current = true;
      setVoiceError(null);
      setState("listening");
    };

    recognition.onend = () => {
      // If we are actively supposed to be listening and it stopped (silent pause timeout)
      if (isListeningRef.current) {
        try {
          recognition.start();
        } catch (e) {
             isListeningRef.current = false;
             setState("idle");
        }
      } else {
        setState((prev) => (prev === "listening" ? "idle" : prev));
        // Hand the mic back to the wake-word ear.
        const st = useStore.getState();
        if (enableWake && st.wakeEnabled) setWakeNonce((n) => n + 1);
      }
    };

    recognition.onerror = (e: any) => {
      const code = (e?.error ?? "") as string;
      if (code === "no-speech" || code === "aborted") {
        // Benign: silence timeout, or our own stop() call. Keep state as-is.
        return;
      }
      console.warn("Speech recognition error:", code);
      isListeningRef.current = false;
      setState("idle");
      if (code === "not-allowed" || code === "service-not-allowed") {
        setVoiceError("blocked");
      } else if (code === "network") {
        setVoiceError("network");
      } else if (code) {
        setVoiceError("error");
      }
    };

    recognitionRef.current = recognition;

    // Cleanup
    return () => {
      try {
        recognition.stop();
      } catch (e) {
        // ignore
      }
    };
  }, [voiceLang, enableWake, wakeEnabled]);

  // Hands-free wake word ("hey rawal") — runs only on the composer's instance.
  useEffect(() => {
    if (!enableWake || !wakeEnabled || typeof window === "undefined") {
      stopWake();
      return;
    }
    const SpeechRecognition = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
    if (!SpeechRecognition) return;

    let disposed = false;
    const rec = new SpeechRecognition();
    rec.continuous = true;
    rec.interimResults = true;
    rec.lang = voiceLang;

    rec.onresult = (event: any) => {
      let text = "";
      for (let i = event.resultIndex; i < event.results.length; i++) {
        text += event.results[i][0].transcript + " ";
      }
      const heard = text.toLowerCase();
      if (heard.includes("hey rawal") || heard.includes("hey rawal") || /(^|\s)rawal(\s|$)/.test(heard)) {
        startListening();
      }
    };
    rec.onstart = () => {
      if (!disposed) setWakeActive(true);
    };
    rec.onend = () => {
      setWakeActive(false);
      // Keep the ear open unless the main mic took over or we were disposed.
      if (!disposed && !isListeningRef.current) {
        try {
          rec.start();
        } catch (e) {}
      }
    };
    rec.onerror = () => {};

    wakeRef.current = rec;
    try {
      rec.start();
    } catch (e) {}

    return () => {
      disposed = true;
      try {
        rec.stop();
      } catch (e) {}
      if (wakeRef.current === rec) wakeRef.current = null;
    };
  }, [enableWake, wakeEnabled, voiceLang, wakeNonce, startListening, stopWake]);

  return {
    state,
    transcript,
    interim,
    wakeActive,
    supported,
    secureContext,
    ttsSupported,
    voiceError,
    clearVoiceError: () => setVoiceError(null),
    voiceLang,
    setVoiceLang: (lang: string) => {
      localStorage.setItem("rawal.voiceLang", lang);
      setVoiceLang(lang);
    },
    selectedVoice,
    availableVoices,
    setSelectedVoice,
    startListening,
    stopListening,
    pauseListening,
    interruptSpeech,
    toggleListening,
    speak,
  };
}