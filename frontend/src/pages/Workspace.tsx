import { Gauge, RefreshCw, Sparkles, WifiOff } from "lucide-react";
import { useState } from "react";
import { DesktopWorkspace } from "@/pages/DesktopWorkspace";
import { MobileWorkspace } from "@/pages/MobileWorkspace";
import { useNetworkAdaptive } from "@/hooks/useNetworkAdaptive";
import { useStore } from "@/lib/store";
import { api } from "@/lib/api";

function NetworkStatusBar() {
  const effectiveNetworkMode = useStore((s) => s.effectiveNetworkMode);
  const networkStats = useStore((s) => s.networkStats);
  const outbox = useStore((s) => s.outbox);
  const flushOutbox = useStore((s) => s.flushOutbox);
  const [retrying, setRetrying] = useState(false);
  const visible = !networkStats.isOnline || effectiveNetworkMode === "ultra_low" || outbox.length > 0;
  if (!visible) return null;

  const offline = !networkStats.isOnline;
  const label = offline ? "Offline mode" : effectiveNetworkMode === "ultra_low" ? "Low-speed mode" : "Sync paused";
  const detail = offline
    ? "Your chat draft is safe. Messages will send when the connection returns."
    : outbox.length > 0
      ? `${outbox.length} message${outbox.length === 1 ? "" : "s"} waiting to sync.`
      : "Heavy previews are paused to keep the agent responsive.";

  return (
    <div role="status" className="flex shrink-0 items-center gap-2 border-b border-amber-500/20 bg-amber-500/[.07] px-3 py-1.5 text-[11px] text-amber-700 dark:text-amber-300">
      {offline ? <WifiOff className="size-3.5 shrink-0" /> : <Gauge className="size-3.5 shrink-0" />}
      <span className="font-medium">{label}</span>
      <span className="hidden min-w-0 truncate sm:inline">· {detail}</span>
      <button type="button" disabled={retrying} onClick={() => { setRetrying(true); void api.health().then(() => flushOutbox()).finally(() => setRetrying(false)); }} className="ml-auto inline-flex shrink-0 items-center gap-1 rounded-md px-2 py-0.5 font-medium hover:bg-amber-500/10 disabled:opacity-60">
        <RefreshCw className={`size-3 ${retrying ? "animate-spin" : ""}`} /> Retry
      </button>
    </div>
  );
}

export function Workspace() {
  const ready = useStore((s) => s.ready);
  const effectiveDeviceMode = useStore((s) => s.effectiveDeviceMode);

  useNetworkAdaptive();

  if (!ready) {
    return (
      <div className="flex h-full items-center justify-center">
        <span className="flex size-10 animate-pulse items-center justify-center rounded-xl bg-primary/15 text-primary">
          <Sparkles className="size-5" />
        </span>
      </div>
    );
  }

  if (effectiveDeviceMode === "mobile") {
    return <div className="flex h-full min-h-0 flex-col"><NetworkStatusBar /><MobileWorkspace /></div>;
  }

  return <div className="flex h-full min-h-0 flex-col"><NetworkStatusBar /><DesktopWorkspace /></div>;
}
