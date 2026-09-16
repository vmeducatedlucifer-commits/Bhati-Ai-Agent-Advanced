import { useEffect, useRef, useState } from "react";
import { Toaster } from "sonner";
import { Login } from "@/pages/Login";
import { LockScreen } from "@/pages/LockScreen";
import { ShareView } from "@/pages/ShareView";
import { Workspace } from "@/pages/Workspace";
import { TooltipProvider } from "@/components/ui/primitives";
import { api, getToken, withTimeout } from "@/lib/api";
import { useStore } from "@/lib/store";
import { useTheme } from "@/hooks/useTheme";
import { Sparkles } from "lucide-react";

type Gate = "checking" | "login" | "app" | "offline";

function shareTokenFromPath(): string | null {
  const match = window.location.pathname.match(/^\/s\/([A-Za-z0-9_-]+)/);
  return match ? match[1] : null;
}

// Each boot step may hang (cold start / redeploy), so cap it and retry:
// ~12 attempts × (15s + 3s) covers even slow Render free-tier wakes.
function bootTimeoutMs(): number {
  const connection = (navigator as Navigator & { connection?: { effectiveType?: string; rtt?: number; saveData?: boolean } }).connection;
  const slow = connection?.saveData || connection?.effectiveType === "slow-2g" || connection?.effectiveType === "2g" || (connection?.rtt ?? 0) > 900;
  return slow ? 60_000 : 30_000;
}
const BOOT_RETRY_DELAY_MS = 3_000;
const BOOT_MAX_ATTEMPTS = 12;

export default function App() {
  const [gate, setGate] = useState<Gate>("checking");
  const [bootNote, setBootNote] = useState("");
  const bootRun = useRef(0);
  const [shareToken] = useState<string | null>(() => shareTokenFromPath());
  const bootstrap = useStore((s) => s.bootstrap);
  const flushOutbox = useStore((s) => s.flushOutbox);
  const setDraft = useStore((s) => s.setDraft);
  const setInstallEvt = useStore((s) => s.setInstallEvt);
  const lockHash = useStore((s) => s.lockHash);
  const unlocked = useStore((s) => s.unlocked);
  const { theme } = useTheme();

  // Boot can outlast a hanging connection (Render free-tier cold starts and
  // redeploys accept TCP but answer only after 30s+), so every step has a
  // timeout and we keep retrying with visible progress instead of an
  // eternal "Connecting" spinner.
  const check = async (attempt = 1): Promise<void> => {
    const run = attempt === 1 ? ++bootRun.current : bootRun.current;
    const alive = () => run === bootRun.current;
    if (attempt === 1) setBootNote("");
    else setBootNote(`Waking up the server… (attempt ${attempt})`);
    try {
      const timeout = bootTimeoutMs();
      const health = await withTimeout(api.health(), timeout, "Health check");
      if (!alive()) return;
      if (health.auth_required && !getToken()) {
        setBootNote("");
        setGate("login");
        return;
      }
      await withTimeout(bootstrap(), timeout, "Loading workspace");
      if (!alive()) return;
      setBootNote("");
      setGate("app");
    } catch {
      if (!alive()) return;
      if (attempt < BOOT_MAX_ATTEMPTS) {
        setBootNote(
          attempt === 1
            ? "Waking up the server…"
            : `Waking up the server… (attempt ${attempt + 1})`,
        );
        await new Promise((resolve) => window.setTimeout(resolve, BOOT_RETRY_DELAY_MS));
        if (!alive()) return;
        return check(attempt + 1);
      }
      setBootNote("");
      setGate("offline");
    }
  };

  useEffect(() => {
    // PWA share-target (?text= / ?title=) → prefill the composer.
    try {
      const params = new URLSearchParams(window.location.search);
      const shared = [params.get("title"), params.get("text"), params.get("url")]
        .filter(Boolean)
        .join("\n");
      if (shared) {
        setDraft(shared);
        window.history.replaceState(null, "", window.location.pathname);
      }
    } catch {
      /* ignore */
    }

    // Desktop/PWA install prompt capture.
    const onInstall = (e: Event) => {
      e.preventDefault();
      setInstallEvt(e);
    };
    // Offline queue flush on reconnect.
    const onOnline = () => {
      void flushOutbox();
      if (gate === "offline") void check();
    };
    window.addEventListener("beforeinstallprompt", onInstall);
    window.addEventListener("online", onOnline);
    void check();
    return () => {
      window.removeEventListener("beforeinstallprompt", onInstall);
      window.removeEventListener("online", onOnline);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Public share links need no login or backend-gate.
  if (shareToken) {
    return (
      <TooltipProvider delayDuration={250}>
        <Toaster theme={theme} position="bottom-right" richColors closeButton />
        <ShareView token={shareToken} />
      </TooltipProvider>
    );
  }

  // App lock (PIN) — session-scoped unlock.
  if (lockHash && !unlocked && gate === "app") {
    return (
      <TooltipProvider delayDuration={250}>
        <Toaster theme={theme} position="bottom-right" richColors closeButton />
        <LockScreen />
      </TooltipProvider>
    );
  }

  return (
    <TooltipProvider delayDuration={250}>
      <Toaster theme={theme} position="bottom-right" richColors closeButton />
      {gate === "checking" && (
        <div className="relative flex h-full flex-col items-center justify-center gap-4 overflow-hidden">
          <span className="orb left-1/2 top-1/3 size-72 -translate-x-1/2 bg-primary/15 animate-orb-drift" />
          <span className="relative flex size-14 items-center justify-center rounded-3xl bg-primary/15 text-primary glow-soft">
            <Sparkles className="size-7 animate-glow-pulse" />
            <span className="absolute inset-0 rounded-3xl border border-primary/40 animate-pulse-ring" />
          </span>
          <div className="relative flex items-center gap-2 text-sm text-muted-foreground">
            {bootNote || "Connecting"}
            <span className="flex items-center gap-1">
              <span className="size-1.5 rounded-full bg-primary animate-typing-dot" />
              <span className="size-1.5 rounded-full bg-primary animate-typing-dot [animation-delay:150ms]" />
              <span className="size-1.5 rounded-full bg-primary animate-typing-dot [animation-delay:300ms]" />
            </span>
          </div>
          {bootNote ? (
            <button
              type="button"
              onClick={() => void check()}
              className="relative rounded-xl border border-border px-4 py-1.5 text-[13px] text-muted-foreground transition-colors hover:text-foreground"
            >
              Retry now
            </button>
          ) : null}
        </div>
      )}
      {gate === "login" && <Login onSignedIn={() => void check()} />}
      {gate === "app" && <Workspace />}
      {gate === "offline" && (
        <div className="relative flex h-full flex-col items-center justify-center gap-3 overflow-hidden px-6 text-center">
          <span className="orb left-[20%] top-[20%] size-64 bg-danger/10 animate-orb-drift" />
          <span className="rise-stagger stagger-1 relative flex size-14 items-center justify-center rounded-3xl bg-danger/10 text-danger animate-float">
            <Sparkles className="size-6" />
          </span>
          <p className="rise-stagger stagger-2 relative text-base font-semibold">Cannot reach the backend</p>
          <p className="rise-stagger stagger-3 relative max-w-md text-[13px] leading-relaxed text-muted-foreground">
            Start it with <code className="rounded bg-muted px-1.5 py-0.5 font-mono">uvicorn app.main:app</code> in{" "}
            <code className="rounded bg-muted px-1.5 py-0.5 font-mono">backend/</code>, or set{" "}
            <code className="rounded bg-muted px-1.5 py-0.5 font-mono">VITE_API_URL</code> to where it runs.
          </p>
          <button
            type="button"
            onClick={() => {
              setGate("checking");
              void check();
            }}
            className="rise-stagger stagger-4 lift relative mt-2 rounded-xl bg-primary px-5 py-2 text-sm font-medium text-primary-foreground glow-soft"
          >
            Retry connection
          </button>
        </div>
      )}
    </TooltipProvider>
  );
}
