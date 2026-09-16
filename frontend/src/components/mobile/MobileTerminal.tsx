import { useEffect, useRef, useState } from "react";
import { CornerDownLeft, Copy, Terminal as TermIcon, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { hapticLight, hapticMedium } from "@/lib/haptics";
import { useStore } from "@/lib/store";

const SHORTCUT_KEYS = ["ESC", "TAB", "CTRL", "↑", "↓", "|", "/", "-", "~", "$", "&&"];

const QUICK_COMMANDS = [
  "ls -la",
  "git status",
  "git log -n 3 --oneline",
  "npm run build",
  "python --version",
  "df -h",
];

export function MobileTerminal() {
  const terminalLines = useStore((s) => s.terminalLines);
  const clearTerminal = useStore((s) => s.clearTerminal);
  const send = useStore((s) => s.send);
  const running = useStore((s) => s.running);

  const [cmdInput, setCmdInput] = useState("");
  const [history, setHistory] = useState<string[]>([]);
  const [historyIndex, setHistoryIndex] = useState(-1);
  const endRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [terminalLines]);

  const handleRunCommand = (cmd: string) => {
    const trimmed = cmd.trim();
    if (!trimmed) return;
    hapticMedium();
    setHistory((prev) => [trimmed, ...prev.slice(0, 30)]);
    setHistoryIndex(-1);
    void send(`Please execute this shell command in terminal: \`${trimmed}\``);
    setCmdInput("");
  };

  const handleVirtualKey = (key: string) => {
    hapticLight();
    if (key === "ESC") {
      setCmdInput("");
    } else if (key === "TAB") {
      setCmdInput((prev) => prev + "  ");
    } else if (key === "↑") {
      if (history.length > 0 && historyIndex < history.length - 1) {
        const next = historyIndex + 1;
        setHistoryIndex(next);
        setCmdInput(history[next]);
      }
    } else if (key === "↓") {
      if (historyIndex > 0) {
        const next = historyIndex - 1;
        setHistoryIndex(next);
        setCmdInput(history[next]);
      } else if (historyIndex === 0) {
        setHistoryIndex(-1);
        setCmdInput("");
      }
    } else {
      setCmdInput((prev) => prev + (key === "$ " ? "$" : key + " "));
    }
    inputRef.current?.focus();
  };

  return (
    <div className="flex h-full flex-col bg-[#0c0d0e] font-mono text-[12px] pb-16">
      {/* Mobile Terminal Header */}
      <div className="flex items-center justify-between border-b border-white/10 bg-[#121316] px-3 py-2">
        <div className="flex items-center gap-2">
          <TermIcon className="size-4 text-emerald-400" />
          <span className="font-semibold text-zinc-100">Linux Sandbox Terminal</span>
          {running && (
            <span className="flex items-center gap-1 rounded-full bg-emerald-500/10 px-2 py-0.5 text-[10.5px] text-emerald-400">
              <span className="size-1.5 animate-pulse rounded-full bg-emerald-400" />
              Active
            </span>
          )}
        </div>
        <div className="flex items-center gap-1">
          <Button
            variant="ghost"
            size="xs"
            onClick={() => {
              hapticLight();
              void navigator.clipboard.writeText(terminalLines.join(""));
            }}
            title="Copy Output"
            className="h-7 text-xs text-zinc-400 hover:text-zinc-100"
          >
            <Copy className="size-3.5" />
          </Button>
          <Button
            variant="ghost"
            size="xs"
            onClick={() => {
              hapticLight();
              clearTerminal();
            }}
            title="Clear Output"
            className="h-7 text-xs text-zinc-400 hover:text-danger"
          >
            <Trash2 className="size-3.5" />
          </Button>
        </div>
      </div>

      {/* Quick Command Chips */}
      <div className="flex items-center gap-1.5 overflow-x-auto border-b border-white/5 bg-black/40 px-2.5 py-1.5 scrollbar-none">
        {QUICK_COMMANDS.map((cmd) => (
          <button
            key={cmd}
            type="button"
            onClick={() => handleRunCommand(cmd)}
            className="shrink-0 rounded-md border border-white/10 bg-[#1a1c22] px-2.5 py-1 text-[11px] text-zinc-300 transition active:scale-95 hover:border-emerald-500/60 hover:text-white font-mono"
          >
            ${cmd}
          </button>
        ))}
      </div>

      {/* Terminal Screen (AMOLED / Termux styled) */}
      <div className="min-h-0 flex-1 overflow-y-auto bg-black p-3 text-zinc-200">
        {terminalLines.length === 0 ? (
          <div className="py-12 text-center text-zinc-600">
            <TermIcon className="mx-auto size-8 opacity-30 text-emerald-500" />
            <p className="mt-2 text-xs">Terminal is ready for execution.</p>
            <p className="text-[11px] text-zinc-600">Commands will stream live in real-time.</p>
          </div>
        ) : (
          <pre className="whitespace-pre-wrap break-all font-mono leading-relaxed text-[11.5px] text-zinc-200">
            {terminalLines.join("")}
          </pre>
        )}
        <div ref={endRef} />
      </div>

      {/* Developer Virtual Keyboard Toolbar (Termux style) */}
      <div className="flex items-center gap-1 overflow-x-auto border-t border-white/10 bg-[#14161b] px-2 py-1 scrollbar-none">
        {SHORTCUT_KEYS.map((k) => (
          <button
            key={k}
            type="button"
            onClick={() => handleVirtualKey(k)}
            className="flex h-7 min-w-[32px] shrink-0 items-center justify-center rounded border border-white/10 bg-[#1f2229] px-2 text-[11px] font-bold text-zinc-300 transition active:scale-90 hover:bg-white/10 active:bg-emerald-500 active:text-black"
          >
            {k}
          </button>
        ))}
      </div>

      {/* Bottom Command Prompt Input */}
      <div className="border-t border-white/10 bg-[#121316] p-2">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            handleRunCommand(cmdInput);
          }}
          className="flex items-center gap-2"
        >
          <span className="select-none pl-1 font-bold text-emerald-400 font-mono">$</span>
          <input
            ref={inputRef}
            type="text"
            value={cmdInput}
            onChange={(e) => setCmdInput(e.target.value)}
            placeholder="Enter command..."
            className="flex-1 rounded-md border border-white/15 bg-black/70 px-2.5 py-1.5 font-mono text-xs text-zinc-100 outline-hidden focus:border-emerald-500"
            autoCapitalize="off"
            autoCorrect="off"
            spellCheck={false}
          />
          <Button
            type="submit"
            size="xs"
            disabled={!cmdInput.trim() || running}
            className="h-8 gap-1 bg-emerald-600 px-3 text-white hover:bg-emerald-500 font-sans"
          >
            <CornerDownLeft className="size-3.5" />
            <span>Run</span>
          </Button>
        </form>
      </div>
    </div>
  );
}
