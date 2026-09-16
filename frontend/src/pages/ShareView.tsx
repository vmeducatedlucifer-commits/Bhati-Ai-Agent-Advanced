import { Eye, Lock, Sparkles } from "lucide-react";
import { useEffect, useState } from "react";
import { Markdown } from "@/components/chat/Markdown";
import { api } from "@/lib/api";
import type { ChatMessage, Thread } from "@/types";

/** Public read-only view for a shared thread. No login required. */
export function ShareView({ token }: { token: string }) {
  const [thread, setThread] = useState<Thread | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [error, setError] = useState(false);

  useEffect(() => {
    void api
      .viewShare(token)
      .then((res) => {
        setThread(res.thread);
        setMessages(res.messages);
      })
      .catch(() => setError(true));
  }, [token]);

  return (
    <div className="flex h-full flex-col items-center overflow-y-auto scrollbar-thin bg-background">
      <header className="sticky top-0 z-10 flex w-full items-center gap-2 border-b border-border bg-background/85 px-4 py-2.5 backdrop-blur">
        <span className="flex size-7 items-center justify-center rounded-lg bg-primary/15 text-primary">
          <Sparkles className="size-3.5" />
        </span>
        <p className="min-w-0 flex-1 truncate text-[13.5px] font-medium">
          {thread ? thread.title : "Shared conversation"}
        </p>
        <span className="flex items-center gap-1 rounded-full bg-muted px-2 py-0.5 text-[11px] text-muted-foreground">
          <Eye className="size-3" />
          read-only
        </span>
      </header>

      <div className="w-full max-w-3xl px-4 py-6 sm:px-6">
        {error ? (
          <div className="flex flex-col items-center gap-2 py-16 text-center">
            <Lock className="size-8 text-muted-foreground" />
            <p className="font-medium">This link is invalid or was revoked.</p>
            <a href="/" className="text-[13px] text-primary hover:underline">
              Open Rawal AI
            </a>
          </div>
        ) : !thread ? (
          <div className="space-y-3 py-8">
            <div className="skeleton h-5 w-2/3" />
            <div className="skeleton h-24 w-full" />
            <div className="skeleton h-24 w-full" />
          </div>
        ) : (
          messages.map((m, i) => (
            <div key={m.id} className="animate-message-in py-3" style={{ animationDelay: `${Math.min(i, 10) * 40}ms` }}>
              <p className="mb-1 text-[10.5px] font-semibold uppercase tracking-wide text-muted-foreground">
                {m.role}
              </p>
              {m.role === "user" ? (
                <p className="whitespace-pre-wrap text-[15px] leading-relaxed">{m.content}</p>
              ) : (
                <Markdown content={m.content || "(no output)"} />
              )}
            </div>
          ))
        )}
      </div>
    </div>
  );
}
