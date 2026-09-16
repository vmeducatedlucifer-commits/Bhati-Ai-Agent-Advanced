import { useEffect, useRef } from "react";
import { useStore } from "@/lib/store";
import { API_BASE } from "@/lib/api";

interface NetworkInformation extends EventTarget {
  downlink?: number; // Mb/s
  effectiveType?: "slow-2g" | "2g" | "3g" | "4g";
  rtt?: number; // ms
  saveData?: boolean;
  addEventListener(type: string, listener: EventListener): void;
  removeEventListener(type: string, listener: EventListener): void;
}

export function useNetworkAdaptive() {
  const networkMode = useStore((s) => s.networkMode);
  const deviceMode = useStore((s) => s.deviceMode);
  const setEffectiveDeviceMode = useStore((s) => s.setEffectiveDeviceMode);
  const setEffectiveNetworkMode = useStore((s) => s.setEffectiveNetworkMode);
  const updateNetworkStats = useStore((s) => s.updateNetworkStats);
  const pingTimerRef = useRef<number | null>(null);

  // Device mode responsive watcher
  useEffect(() => {
    const handleResize = () => {
      if (deviceMode === "auto") {
        const isMobile = window.innerWidth < 768;
        setEffectiveDeviceMode(isMobile ? "mobile" : "desktop");
      }
    };
    handleResize();
    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  }, [deviceMode, setEffectiveDeviceMode]);

  // Network adaptive speed watcher
  useEffect(() => {
    const nav = typeof navigator !== "undefined" ? navigator : null;
    const conn: NetworkInformation | undefined = (nav as any)?.connection || (nav as any)?.mozConnection || (nav as any)?.webkitConnection;

    const measurePingAndSpeed = async () => {
      if (!navigator.onLine) {
        updateNetworkStats({ isOnline: false });
        return;
      }

      let measuredRtt = 0;
      let effectiveKbps = 10000;
      let effectiveType = conn?.effectiveType || "4g";

      if (conn?.downlink !== undefined && conn.downlink > 0) {
        effectiveKbps = Math.round(conn.downlink * 1024); // Mb/s to kbps
      }
      if (conn?.rtt !== undefined) {
        measuredRtt = conn.rtt;
      }

      // Browser NetworkInformation is often missing or optimistic on Android.
      // Measure a tiny backend request as well so the UI adapts to the actual
      // route between the phone and this agent.
      try {
        const started = performance.now();
        const controller = new AbortController();
        const timeout = window.setTimeout(() => controller.abort(), 8_000);
        try {
          await fetch(`${API_BASE}/api/v1/health`, { cache: "no-store", signal: controller.signal });
        } finally {
          window.clearTimeout(timeout);
        }
        measuredRtt = Math.max(measuredRtt, Math.round(performance.now() - started));
      } catch {
        measuredRtt = Math.max(measuredRtt, 2_000);
      }

      // Use a practical threshold instead of only treating <40 kbps as slow.
      // Many mobile 3G routes report 0.4–1.5 Mbps but still have high latency.
      const isUltraLow =
        effectiveKbps <= 256 ||
        effectiveType === "slow-2g" ||
        effectiveType === "2g" ||
        conn?.saveData === true ||
        measuredRtt > 1200 ||
        (measuredRtt > 700 && effectiveKbps <= 1500);

      updateNetworkStats({
        isOnline: true,
        effectiveType,
        downlink: conn?.downlink ?? 10,
        rtt: measuredRtt,
        effectiveSpeedKbps: effectiveKbps,
      });

      if (networkMode === "auto") {
        setEffectiveNetworkMode(isUltraLow ? "ultra_low" : "high_speed");
      }
    };

    void measurePingAndSpeed();

    const onConnChange = () => {
      void measurePingAndSpeed();
    };

    const onOnline = () => {
      updateNetworkStats({ isOnline: true });
      void measurePingAndSpeed();
    };

    const onOffline = () => {
      updateNetworkStats({ isOnline: false });
    };

    if (conn?.addEventListener) {
      conn.addEventListener("change", onConnChange);
    }
    window.addEventListener("online", onOnline);
    window.addEventListener("offline", onOffline);

    // Periodic lightweight probe every 30 seconds
    pingTimerRef.current = window.setInterval(() => {
      void measurePingAndSpeed();
    }, 30_000);

    return () => {
      if (conn?.removeEventListener) {
        conn.removeEventListener("change", onConnChange);
      }
      window.removeEventListener("online", onOnline);
      window.removeEventListener("offline", onOffline);
      if (pingTimerRef.current) clearInterval(pingTimerRef.current);
    };
  }, [networkMode, setEffectiveNetworkMode, updateNetworkStats]);
}
