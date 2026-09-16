import { Columns2, Loader2, Send } from "lucide-react";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { api, displayModelName } from "@/lib/api";
import { useStore } from "@/lib/store";
import type { ChatMessage } from "@/types";

export function CompareDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (v: boolean) => void }) {
  const threads = useStore((s) => s.threads);
  const activeThreadId = useStore((s) => s.activeThreadId);
  const refreshThreads = useStore((s) => s.refreshThreads);
  const [prompt, setPrompt] = useState("");
  const [otherId, setOtherId] = useState("");
  const [busy, setBusy] = useState(false);
  const [answers, setAnswers] = useState<{ a: ChatMessage[]; b: ChatMessage[] }>({ a: [], b: [] });

  useEffect(() => {
    if (open) {
      const fallback = threads.find((t) => t.id !== activeThreadId)?.id ?? "";
      setOtherId(fallback);
      setAnswers({ a: [], b: [] });
    }
  }, [open, threads, activeThreadId]);

  const latestAssistant = (list: ChatMessage[]) =>
    [...list].reverse().find((m) => m.role === "assistant" && m.content)?.content ?? "(no answer yet)";

  const run = async () => {
    if (!activeThreadId || !otherId || !prompt.trim() || busy) return;
    setBusy(true);
    try {
      await Promise.all([
        api.sendMessage(activeThreadId, prompt),
        api.sendMessage(otherId, prompt),
      ]);
      // Poll both until idle (max ~3 min).
      for (let i = 0; i < 90; i++) {
        await new Promise((r) => setTimeout(r, 2000));
        const [sa, sb] = await Promise.all([
          api.runStatus(activeThreadId).catch(() => ({ running: true })),
          api.runStatus(otherId).catch(() => ({ running: true })),
        ]);
        if (!sa.running && !sb.running) break;
      }
      const [ma, mb] = await Promise.all([api.listMessages(activeThreadId), api.listMessages(otherId)]);
      setAnswers({ a: ma, b: mb });
      void refreshThreads();
    } finally {
      setBusy(false);
    }
  };

  const nameOf = (id: string | null) => threads.find((t) => t.id === id)?.title ?? "—";

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[86vh] w-[min(860px,94vw)] overflow-y-auto scrollbar-thin">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Columns2 className="size-4 text-primary" />
            Compare models side-by-side
          </DialogTitle>
        </DialogHeader>

        <div className="space-y-3">
          <label className="block text-[12px] font-medium">
            Compare with
            <select
              value={otherId}
              onChange={(e) => setOtherId(e.target.value)}
              className="mt-1 h-9 w-full rounded-lg border border-border bg-surface px-3 text-[13px]"
            >
              <option value="">Select a chat…</option>
              {threads
                .filter((t) => t.id !== activeThreadId)
                .map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.title} {t.model ? `(${displayModelName(t.model)})` : ""}
                  </option>
                ))}
            </select>
          </label>
          <div className="flex gap-2">
            <textarea
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              rows={2}
              placeholder="Prompt to run on both chats…"
              className="flex-1 rounded-lg border border-input bg-surface px-3 py-2 text-[13px]"
            />
            <Button onClick={() => void run()} disabled={busy || !prompt.trim() || !otherId}>
              {busy ? <Loader2 className="size-4 animate-spin" /> : <Send className="size-4" />}
              Run both
            </Button>
          </div>

          {(answers.a.length > 0 || answers.b.length > 0 || busy) && (
            <div className="grid gap-3 md:grid-cols-2">
              {(
                [
                  ["A", nameOf(activeThreadId), answers.a],
                  ["B", nameOf(otherId), answers.b],
                ] as const
              ).map(([side, title, list]) => (
                <div key={side} className="rounded-xl border border-border bg-surface p-3">
                  <p className="mb-2 truncate text-[12px] font-semibold">
                    <span className="mr-1.5 rounded bg-primary/15 px-1.5 py-0.5 font-mono text-primary">{side}</span>
                    {title}
                  </p>
                  {busy && list.length === 0 ? (
                    <div className="space-y-2">
                      <div className="skeleton h-3 w-full" />
                      <div className="skeleton h-3 w-5/6" />
                      <div className="skeleton h-3 w-4/6" />
                    </div>
                  ) : (
                    <p className="whitespace-pre-wrap text-[13px] leading-relaxed">{latestAssistant(list)}</p>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
