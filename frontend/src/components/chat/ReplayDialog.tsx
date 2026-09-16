import { History, TerminalSquare } from "lucide-react";
import { useEffect, useState } from "react";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import type { ChatMessage } from "@/types";

export function ReplayDialog({
  open,
  onOpenChange,
  threadId,
  threadTitle,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  threadId: string | null;
  threadTitle: string;
}) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);

  useEffect(() => {
    if (open && threadId) {
      void api.listMessages(threadId).then(setMessages).catch(() => setMessages([]));
    }
  }, [open, threadId]);

  if (!threadId) return null;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[84vh] w-[min(620px,94vw)] overflow-y-auto scrollbar-thin">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <History className="size-4 text-primary" />
            Run replay — “{threadTitle}”
          </DialogTitle>
        </DialogHeader>

        <ol className="relative space-y-4 border-l border-border pl-5">
          {messages.map((m, i) => (
            <li key={m.id} className="relative animate-message-in" style={{ animationDelay: `${Math.min(i, 12) * 40}ms` }}>
              <span className="absolute -left-[26px] top-1 size-2.5 rounded-full bg-primary ring-4 ring-background" />
              <p className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                Step {i + 1} · {m.role}
              </p>
              <p className="mt-0.5 line-clamp-4 whitespace-pre-wrap text-[13px] leading-relaxed">
                {m.content || "(no text)"}
              </p>
              {m.tool_calls.length > 0 && (
                <div className="mt-1.5 flex flex-wrap gap-1.5">
                  {m.tool_calls.map((t) => (
                    <span
                      key={t.id}
                      className={cn(
                        "inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 font-mono text-[10.5px]",
                        t.status === "ok" && "bg-emerald-500/10 text-emerald-500",
                        t.status === "error" && "bg-danger/10 text-danger",
                        t.status === "denied" && "bg-warning/10 text-warning",
                        t.status === "running" && "bg-sky-500/10 text-sky-500",
                      )}
                    >
                      <TerminalSquare className="size-3" />
                      {t.name}
                    </span>
                  ))}
                </div>
              )}
            </li>
          ))}
          {messages.length === 0 ? (
            <p className="text-[13px] text-muted-foreground">No steps yet — send a message first.</p>
          ) : null}
        </ol>
      </DialogContent>
    </Dialog>
  );
}
