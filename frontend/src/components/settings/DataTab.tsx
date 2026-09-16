import { Bell, Database, Fingerprint, Gauge, RefreshCw } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useStore } from "@/lib/store";

export function DataTab() {
  const lowPerf = useStore((s) => s.lowPerf);
  const setLowPerf = useStore((s) => s.setLowPerf);
  const notifyEnabled = useStore((s) => s.notifyEnabled);
  const setNotifyEnabled = useStore((s) => s.setNotifyEnabled);
  const lockHash = useStore((s) => s.lockHash);
  const setPin = useStore((s) => s.setPin);
  const [pinInput, setPinInput] = useState("");

  const handleClearCache = async () => {
    if (confirm("Are you sure? This will remove all local frontend caches and force a fresh reload from the server.")) {
      if ('caches' in window) {
        try {
          const keys = await caches.keys();
          await Promise.all(keys.map(key => caches.delete(key)));
        } catch (e) {
          console.error("Cache clear failed", e);
        }
      }
      // Also unregister service workers to force a clean slate
      if ('serviceWorker' in navigator) {
        try {
          const registrations = await navigator.serviceWorker.getRegistrations();
          for (const reg of registrations) {
            await reg.unregister();
          }
        } catch (e) {}
      }
      window.location.reload();
    }
  };

  return (
    <div className="space-y-4">
      <div>
        <h3 className="text-sm font-semibold tracking-tight">App Data & Cache</h3>
        <p className="text-[12.5px] text-muted-foreground">
          Manage local storage, offline caches, and progressive web app (PWA) data.
        </p>
      </div>

      <div className="rounded-xl border border-border bg-surface p-4">
        <label className="flex items-center gap-2 text-xs font-medium mb-3">
          <Gauge className="size-3.5 text-primary" />
          Performance Mode (low-end devices)
        </label>
        <p className="text-[11px] text-muted-foreground mb-4">
          Disables ambient background effects and floats while keeping chat animations buttery smooth.
          Recommended for older phones or when the UI feels slow. Takes effect instantly.
        </p>
        <Button
          variant={lowPerf ? "default" : "outline"}
          onClick={() => setLowPerf(!lowPerf)}
          className="w-full sm:w-auto"
        >
          {lowPerf ? "Performance Mode: ON" : "Performance Mode: OFF"}
        </Button>
      </div>

      <div className="rounded-xl border border-border bg-surface p-4">
        <label className="flex items-center gap-2 text-xs font-medium mb-3">
          <Fingerprint className="size-3.5 text-primary" />
          App Lock (PIN)
        </label>
        <p className="text-[11px] text-muted-foreground mb-4">
          Lock the app behind a 4–6 digit PIN. Stored as a hash on this device only; unlocking lasts for this browser session.
        </p>
        {lockHash ? (
          <Button variant="outline" onClick={() => void setPin(null)} className="w-full sm:w-auto">
            Remove PIN lock
          </Button>
        ) : (
          <div className="flex gap-2">
            <Input
              value={pinInput}
              onChange={(e) => setPinInput(e.target.value.replace(/[^0-9]/g, "").slice(0, 6))}
              placeholder="4–6 digits"
              inputMode="numeric"
              className="h-9 max-w-40 font-mono text-sm tracking-widest"
            />
            <Button
              disabled={pinInput.length < 4}
              onClick={async () => {
                await setPin(pinInput);
                setPinInput("");
              }}
            >
              Set PIN
            </Button>
          </div>
        )}
      </div>

      <div className="rounded-xl border border-border bg-surface p-4">
        <label className="flex items-center gap-2 text-xs font-medium mb-3">
          <Bell className="size-3.5 text-primary" />
          Notifications
        </label>
        <p className="text-[11px] text-muted-foreground mb-4">
          Get a desktop notification when an agent run finishes while the tab is in the background.
        </p>
        <Button
          variant={notifyEnabled ? "default" : "outline"}
          onClick={() => setNotifyEnabled(!notifyEnabled)}
          className="w-full sm:w-auto"
        >
          {notifyEnabled ? "Notifications: ON" : "Notifications: OFF"}
        </Button>
      </div>

      <div className="rounded-xl border border-border bg-surface p-4">
        <label className="flex items-center gap-2 text-xs font-medium mb-3">
          <Database className="size-3.5 text-primary" />
          Offline Cache (PWA)
        </label>
        <p className="text-[11px] text-muted-foreground mb-4">
          If the app seems stuck on a white screen after an update, or styling isn't loading properly, use this to force download latest assets. This acts like Ctrl+Shift+R for mobile devices.
        </p>
        <Button variant="danger" onClick={handleClearCache} className="w-full sm:w-auto">
          <RefreshCw className="size-3.5 mr-2" />
          Hard Refresh & Clear Cache
        </Button>
      </div>
    </div>
  );
}
