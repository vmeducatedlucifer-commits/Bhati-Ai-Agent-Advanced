import { FitAddon } from "@xterm/addon-fit";
import { WebLinksAddon } from "@xterm/addon-web-links";
import { Terminal } from "@xterm/xterm";
import { Eraser, Plug, RotateCw, Wand2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Badge, Tooltip } from "@/components/ui/primitives";
import { terminalUrl } from "@/lib/api";
import { useStore } from "@/lib/store";

const THEME = {
  background: "#0d0d0c",
  foreground: "#e6e3dd",
  cursor: "#d97757",
  selectionBackground: "#d9775740",
  black: "#1f1e1d",
  red: "#e06c75",
  green: "#98c379",
  yellow: "#e5c07b",
  blue: "#61afef",
  magenta: "#c678dd",
  cyan: "#56b6c2",
  white: "#dcdfe4",
  brightBlack: "#5c6370",
};

/**
 * Two feeds share this terminal: output the agent produced (pushed through the store)
 * and a live shell the user drives over the WebSocket. Both write to the same buffer so
 * the user sees one machine, not two.
 */
export function TerminalView() {
  const containerRef = useRef<HTMLDivElement>(null);
  const termRef = useRef<Terminal | null>(null);
  const fitRef = useRef<FitAddon | null>(null);
  const socketRef = useRef<WebSocket | null>(null);
  const writtenRef = useRef(0);
  const inputRef = useRef("");
  const historyRef = useRef<string[]>([]);
  const historyIndex = useRef(-1);
  const busyRef = useRef(false);

  const [connected, setConnected] = useState(false);
  const threadId = useStore((s) => s.activeThreadId);
  const lines = useStore((s) => s.terminalLines);
  const clear = useStore((s) => s.clearTerminal);
  const sandbox = useStore((s) => s.sandbox);
  const running = useStore((s) => s.running);
  const send = useStore((s) => s.send);

  // ---- terminal instance ------------------------------------------------
  useEffect(() => {
    if (!containerRef.current) return;
    const term = new Terminal({
      fontFamily: "JetBrains Mono, ui-monospace, monospace",
      fontSize: 12.5,
      lineHeight: 1.4,
      cursorBlink: true,
      convertEol: true,
      scrollback: 8000,
      theme: THEME,
      allowProposedApi: true,
    });
    const fit = new FitAddon();
    term.loadAddon(fit);
    term.loadAddon(new WebLinksAddon());
    term.open(containerRef.current);
    setTimeout(() => fit.fit(), 0);

    termRef.current = term;
    fitRef.current = fit;

    const observer = new ResizeObserver(() => {
      try {
        fit.fit();
      } catch {
        /* container hidden */
      }
    });
    observer.observe(containerRef.current);

    return () => {
      observer.disconnect();
      term.dispose();
      termRef.current = null;
    };
  }, []);

  // ---- agent output -----------------------------------------------------
  useEffect(() => {
    const term = termRef.current;
    if (!term) return;
    if (lines.length < writtenRef.current) {
      term.clear();
      writtenRef.current = 0;
    }
    for (let i = writtenRef.current; i < lines.length; i += 1) {
      term.write(lines[i].replace(/\n/g, "\r\n"));
      if (!lines[i].endsWith("\n")) term.write("\r\n");
    }
    writtenRef.current = lines.length;
  }, [lines]);

  // ---- interactive shell ------------------------------------------------
  useEffect(() => {
    if (!threadId) return;
    const term = termRef.current;
    if (!term) return;

    const socket = new WebSocket(terminalUrl(threadId));
    socketRef.current = socket;

    const prompt = () => term.write("\x1b[38;5;208m$\x1b[0m ");

    socket.onopen = () => setConnected(true);
    socket.onclose = () => setConnected(false);
    socket.onerror = () => setConnected(false);
    socket.onmessage = (event) => {
      const message = JSON.parse(event.data as string);
      if (message.type === "ready") {
        term.writeln(
          `\x1b[38;5;244mconnected to ${message.backend} sandbox · ${message.workspace}\x1b[0m`,
        );
        prompt();
      } else if (message.type === "output") {
        term.write(String(message.chunk).replace(/\n/g, "\r\n"));
      } else if (message.type === "end") {
        busyRef.current = false;
        term.write("\r\n");
        prompt();
      } else if (message.type === "error") {
        term.writeln(`\x1b[31m${message.message}\x1b[0m`);
      }
    };

    const disposable = term.onData((data) => {
      if (socket.readyState !== WebSocket.OPEN) return;
      if (busyRef.current) {
        if (data === "\u0003") socket.send(JSON.stringify({ type: "interrupt" }));
        return;
      }
      switch (data) {
        case "\r": {
          const command = inputRef.current.trim();
          term.write("\r\n");
          inputRef.current = "";
          historyIndex.current = -1;
          if (!command) {
            prompt();
            return;
          }
          historyRef.current.push(command);
          busyRef.current = true;
          socket.send(JSON.stringify({ type: "run", command }));
          return;
        }
        case "\u007f": {
          if (inputRef.current.length > 0) {
            inputRef.current = inputRef.current.slice(0, -1);
            term.write("\b \b");
          }
          return;
        }
        case "\u0003": {
          term.write("^C\r\n");
          inputRef.current = "";
          prompt();
          return;
        }
        case "\u001b[A": {
          const history = historyRef.current;
          if (!history.length) return;
          historyIndex.current = historyIndex.current < 0 ? history.length - 1 : Math.max(0, historyIndex.current - 1);
          const recalled = history[historyIndex.current];
          term.write("\r\x1b[K");
          prompt();
          term.write(recalled);
          inputRef.current = recalled;
          return;
        }
        case "\u001b[B": {
          const history = historyRef.current;
          if (historyIndex.current < 0) return;
          historyIndex.current = Math.min(history.length - 1, historyIndex.current + 1);
          const recalled = history[historyIndex.current] ?? "";
          term.write("\r\x1b[K");
          prompt();
          term.write(recalled);
          inputRef.current = recalled;
          return;
        }
        default: {
          if (data >= " " || data === "\t") {
            inputRef.current += data;
            term.write(data);
          }
        }
      }
    });

    return () => {
      disposable.dispose();
      socket.close();
      socketRef.current = null;
    };
  }, [threadId]);

  return (
    <div className="flex h-full flex-col bg-[#0d0d0c]">
      <div className="flex items-center gap-2 border-b border-white/10 px-3 py-1.5">
        <Badge tone={connected ? "success" : "muted"}>
          <Plug className="size-3" />
          {connected ? "live" : "offline"}
        </Badge>
        {sandbox?.image ? (
          <span className="truncate font-mono text-[11px] text-white/40">{sandbox.image}</span>
        ) : null}
        <div className="ml-auto flex items-center gap-1">
          <Tooltip content="Auto-fix: run last command/tests and fix until green (max 5 rounds)">
            <Button
              variant="ghost"
              size="icon-sm"
              className="text-white/50 hover:bg-white/10 hover:text-white"
              disabled={running || !threadId}
              onClick={() =>
                void send(
                  "Auto-fix loop: re-run the last failing command or test suite from terminal history, diagnose the failure, patch the code, and repeat until everything passes (max 5 rounds). Summarize each round briefly.",
                )
              }
            >
              <Wand2 className="size-3.5" />
            </Button>
          </Tooltip>
          <Tooltip content="Clear">
            <Button
              variant="ghost"
              size="icon-sm"
              className="text-white/50 hover:bg-white/10 hover:text-white"
              onClick={() => {
                clear();
                termRef.current?.clear();
                writtenRef.current = 0;
              }}
            >
              <Eraser className="size-3.5" />
            </Button>
          </Tooltip>
          <Tooltip content="Refit">
            <Button
              variant="ghost"
              size="icon-sm"
              className="text-white/50 hover:bg-white/10 hover:text-white"
              onClick={() => fitRef.current?.fit()}
            >
              <RotateCw className="size-3.5" />
            </Button>
          </Tooltip>
        </div>
      </div>
      <div ref={containerRef} className="min-h-0 flex-1 px-2 py-1.5" />
    </div>
  );
}
