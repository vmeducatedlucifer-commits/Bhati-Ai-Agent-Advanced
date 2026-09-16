import {
  ArrowLeft,
  ArrowRight,
  Camera,
  ExternalLink,
  Globe,
  Keyboard,
  MousePointer2,
  Play,
  RotateCw,
  Send,
  Square,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { BrowserAutomationBar } from "@/components/computer/BrowserAutomationBar";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { api, browserStreamUrl } from "@/lib/api";
import { useStore } from "@/lib/store";
import { previewUrlWithTicket } from "@/lib/api";

/** Resolve a relative preview path or localhost/127.0.0.1 link to the backend reverse proxy */
function resolvePreviewBase(url: string | null, activeThreadId: string | null): {
  url: string | null;
  threadId: string | null;
  port: number | null;
} {
  if (!url) return { url: null, threadId: null, port: null };
  const base = import.meta.env.VITE_API_URL ?? window.location.origin;
  const localMatch = url.match(/^https?:\/\/(?:localhost|127\.0\.0\.1|0\.0\.0\.0):(\d+)([\/?].*)?$/i);
  if (localMatch && activeThreadId) {
    const port = localMatch[1];
    const rest = (localMatch[2] || "/").replace(/^\//, "");
    return { url: `${base.replace(/\/$/, "")}/api/v1/preview/${activeThreadId}/${port}/${rest}`, threadId: activeThreadId, port: Number(port) };
  }
  if (url.startsWith("/")) {
    const full = base.replace(/\/$/, "") + url;
    const pvMatch = full.match(/\/api\/v1\/preview\/([^/]+)\/(\d+)\//);
    return { url: full, threadId: pvMatch ? pvMatch[1] : null, port: pvMatch ? Number(pvMatch[2]) : null };
  }
  return { url, threadId: null, port: null };
}

type LiveImage = { image_base64: string; url: string; title: string; width: number; height: number };

export function BrowserView() {
  const rawBrowserUrl = useStore((s) => s.browserUrl);
  const activeThreadId = useStore((s) => s.activeThreadId);
  const navigate = useStore((s) => s.navigateBrowser);
  const base = resolvePreviewBase(rawBrowserUrl, activeThreadId);
  const [browserUrl, setBrowserUrl] = useState<string | null>(null);
  const [value, setValue] = useState(base.url ?? "");
  const [loading, setLoading] = useState(Boolean(base.url));
  const [nonce, setNonce] = useState(0);
  const [live, setLive] = useState(false);
  const [liveImage, setLiveImage] = useState<LiveImage | null>(null);
  const [liveBusy, setLiveBusy] = useState(false);
  const [liveError, setLiveError] = useState("");
  const [streamState, setStreamState] = useState<"connecting" | "live" | "fallback">("connecting");
  const [typing, setTyping] = useState("");
  const frameRef = useRef<HTMLIFrameElement>(null);
  const imageRef = useRef<HTMLImageElement>(null);
  const streamRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function attachTicket() {
      if (!base.url) {
        if (!cancelled) { setBrowserUrl(null); setValue(""); setLoading(false); }
        return;
      }
      if (!cancelled) setLoading(true);
      if (base.threadId && base.port) {
        try {
          const prefixMatch = base.url.match(/^(.+\/api\/v1\/preview\/[^/]+\/\d+\/)(.*)$/);
          const rest = (prefixMatch ? prefixMatch[2] : "").split("?")[0].replace(/^\//, "");
          const finalUrl = await previewUrlWithTicket(base.threadId, base.port, rest);
          if (!cancelled) { setBrowserUrl(finalUrl); setValue(finalUrl); setLoading(false); }
          return;
        } catch { /* fall through to bare URL */ }
      }
      if (!cancelled) { setBrowserUrl(base.url); setValue(base.url); setLoading(false); }
    }
    void attachTicket();
    return () => { cancelled = true; };
  }, [rawBrowserUrl, activeThreadId]);

  const refreshLive = async () => {
    if (!activeThreadId) return;
    try {
      const shot = await api.browserScreenshot(activeThreadId);
      setLiveImage(shot);
      setValue(shot.url);
      setLiveError("");
    } catch (error) {
      setLiveError(error instanceof Error ? error.message : "Browser screenshot failed");
    }
  };

  useEffect(() => {
    if (!live || !activeThreadId) return;
    setStreamState("connecting");
    const socket = new WebSocket(browserStreamUrl(activeThreadId));
    streamRef.current = socket;
    socket.onopen = () => setStreamState("live");
    socket.onmessage = (event) => {
      try {
        const message = JSON.parse(event.data) as LiveImage & { type: string; message?: string };
        if (message.type === "frame") {
          setLiveImage(message);
          setValue(message.url);
          setLiveError("");
        } else if (message.type === "error" || message.type === "action_error") {
          setLiveError(message.message || "Browser stream error");
        }
      } catch {
        setLiveError("Invalid browser stream frame");
      }
    };
    socket.onerror = () => {
      setStreamState("fallback");
      setLiveError("Realtime stream unavailable; using screenshot fallback.");
      void refreshLive();
    };
    socket.onclose = () => {
      streamRef.current = null;
      setStreamState("fallback");
    };
    return () => {
      socket.close();
      streamRef.current = null;
    };
  }, [live, activeThreadId]);

  const startLive = async () => {
    if (!activeThreadId) return;
    setLiveBusy(true);
    setLiveError("");
    try {
      const info = await api.browserStart(activeThreadId);
      setLive(true);
      setValue(info.url || "about:blank");
    } catch (error) {
      setLiveError(error instanceof Error ? error.message : "Could not start Chromium");
    } finally { setLiveBusy(false); }
  };

  const stopLive = async () => {
    if (!activeThreadId) return;
    setLiveBusy(true);
    try { streamRef.current?.close(); await api.browserStop(activeThreadId); setLive(false); setLiveImage(null); }
    catch (error) { setLiveError(error instanceof Error ? error.message : "Could not stop Chromium"); }
    finally { setLiveBusy(false); }
  };

  const go = async () => {
    let target = value.trim();
    if (!target) return;
    if (!/^https?:\/\//i.test(target) && !target.startsWith("/")) target = `https://${target}`;
    if (live && activeThreadId) {
      setLiveBusy(true);
      try {
        if (streamRef.current?.readyState === WebSocket.OPEN) {
          streamRef.current.send(JSON.stringify({ type: "navigate", url: target }));
        } else {
          const result = await api.browserNavigate(activeThreadId, target);
          setValue(result.url);
          await refreshLive();
        }
      }
      catch (error) { setLiveError(error instanceof Error ? error.message : "Navigation failed"); }
      finally { setLiveBusy(false); }
    } else {
      navigate(target);
      setNonce((n) => n + 1);
    }
  };

  const clickLive = async (event: React.MouseEvent<HTMLImageElement>) => {
    if (!live || !activeThreadId || !liveImage || !imageRef.current) return;
    const rect = imageRef.current.getBoundingClientRect();
    const x = Math.round(((event.clientX - rect.left) / rect.width) * liveImage.width);
    const y = Math.round(((event.clientY - rect.top) / rect.height) * liveImage.height);
    if (streamRef.current?.readyState === WebSocket.OPEN) {
      streamRef.current.send(JSON.stringify({ type: "click", x, y }));
    } else {
      await api.browserClick(activeThreadId, x, y);
      await refreshLive();
    }
  };

  const typeLive = async () => {
    if (!activeThreadId || !typing) return;
    if (streamRef.current?.readyState === WebSocket.OPEN) {
      streamRef.current.send(JSON.stringify({ type: "type", text: typing }));
    } else await api.browserType(activeThreadId, typing);
    setTyping("");
    if (!streamRef.current || streamRef.current.readyState !== WebSocket.OPEN) await refreshLive();
  };

  const pressLive = async (key: string) => {
    if (!activeThreadId) return;
    if (streamRef.current?.readyState === WebSocket.OPEN) {
      streamRef.current.send(JSON.stringify({ type: "press", key }));
    } else {
      await api.browserPress(activeThreadId, key);
      await refreshLive();
    }
  };

  return (
    <div className="flex h-full flex-col">
      <BrowserAutomationBar currentUrl={value} />
      <div className="flex flex-wrap items-center gap-1.5 border-b border-border px-2 py-1.5">
        <Button variant="ghost" size="icon-sm" onClick={() => !live && frameRef.current?.contentWindow?.history.back()} disabled={live}><ArrowLeft className="size-3.5" /></Button>
        <Button variant="ghost" size="icon-sm" onClick={() => !live && frameRef.current?.contentWindow?.history.forward()} disabled={live}><ArrowRight className="size-3.5" /></Button>
        <Button variant="ghost" size="icon-sm" onClick={() => live ? void refreshLive() : setNonce((n) => n + 1)}><RotateCw className="size-3.5" /></Button>
        <Input value={value} onChange={(e) => setValue(e.target.value)} onKeyDown={(e) => e.key === "Enter" && void go()} placeholder="URL or address" className="h-7 min-w-[180px] flex-1 rounded-full text-[12.5px]" />
        <Button size="sm" variant={live ? "secondary" : "outline"} onClick={() => live ? void stopLive() : void startLive()} disabled={!activeThreadId || liveBusy} className="h-7 shrink-0 text-[10.5px]">
          {live ? <><Square className="size-3" /> Stop live</> : <><Play className="size-3" /> Live Chromium</>}
        </Button>
        {!live && browserUrl ? <Button variant="ghost" size="icon-sm" asChild><a href={browserUrl} target="_blank" rel="noreferrer" title="Open in new tab"><ExternalLink className="size-3.5" /></a></Button> : null}
      </div>

      {live ? (
        <div className="min-h-0 flex-1 overflow-auto bg-zinc-950">
          <div className="flex min-h-full flex-col items-center justify-center gap-3 p-3">
            {liveImage ? <img ref={imageRef} src={`data:${streamState === "live" ? "image/jpeg" : "image/png"};base64,${liveImage.image_base64}`} onClick={(e) => void clickLive(e)} onWheel={(e) => { e.preventDefault(); if (activeThreadId && streamRef.current?.readyState === WebSocket.OPEN) streamRef.current.send(JSON.stringify({ type: "scroll", delta_y: e.deltaY })); else if (activeThreadId) void api.browserScroll(activeThreadId, e.deltaY).then(refreshLive); }} alt={liveImage.title || "Live Chromium page"} className="max-h-[calc(100vh-250px)] w-full cursor-crosshair select-none object-contain shadow-2xl" draggable={false} /> : <div className="flex items-center gap-2 py-16 text-sm text-zinc-400"><Camera className="size-4" /> Starting Chromium…</div>}
            <div className="flex w-full max-w-3xl flex-wrap items-center gap-1.5 rounded-xl border border-white/10 bg-white/[0.06] p-2">
              <MousePointer2 className="ml-1 size-3.5 text-primary" />
              <span className="mr-1 text-[10px] text-zinc-400">Click the page</span>
              <Keyboard className="ml-2 size-3.5 text-primary" />
              <Input value={typing} onChange={(e) => setTyping(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") void typeLive(); }} placeholder="Type into focused element…" className="h-7 min-w-[180px] flex-1 border-white/10 bg-black/20 text-[11px] text-white" />
              <Button size="icon-sm" variant="secondary" onClick={() => void typeLive()} disabled={!typing}><Send className="size-3.5" /></Button>
              <Button size="sm" variant="ghost" onClick={() => void pressLive("Enter")} className="h-7 text-[10px]">Enter</Button>
              <Button size="sm" variant="ghost" onClick={() => void pressLive("Escape")} className="h-7 text-[10px]">Esc</Button>
            </div>
            <p className="text-[10px] text-zinc-500">{streamState === "live" ? "Live WebSocket stream" : streamState === "fallback" ? "Screenshot fallback" : "Connecting to browser stream…"}</p>
            {liveError ? <p className="text-[11px] text-red-300">{liveError}</p> : null}
          </div>
        </div>
      ) : (
        <div className="min-h-0 flex-1 bg-white dark:bg-zinc-900">
          {loading ? <div className="flex h-full flex-col items-center justify-center gap-2 text-center text-muted-foreground"><RotateCw className="size-6 animate-spin opacity-60" /><p className="max-w-xs text-[13px]">Loading live preview…</p></div> : browserUrl ? <iframe key={`${browserUrl}-${nonce}`} ref={frameRef} src={browserUrl} title="Preview" className="size-full border-0" sandbox="allow-scripts allow-same-origin allow-forms allow-popups allow-modals" /> : <div className="flex h-full flex-col items-center justify-center gap-2 text-center text-muted-foreground"><Globe className="size-8 opacity-40" /><p className="max-w-xs text-[13px]">Open Live Chromium for real mouse and keyboard automation, or start a project preview.</p></div>}
        </div>
      )}
    </div>
  );
}
