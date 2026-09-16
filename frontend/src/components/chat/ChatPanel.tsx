import { ArrowDown, Search, Sparkles } from "lucide-react";
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { ChatSearch } from "@/components/chat/ChatSearch";
import { Composer } from "@/components/chat/Composer";
import { LiveAgentProgress } from "@/components/chat/LiveAgentProgress";
import { MessageBubble } from "@/components/chat/MessageBubble";
import { PermissionPrompt } from "@/components/chat/PermissionPrompt";
import { Button } from "@/components/ui/button";
import { useStore } from "@/lib/store";
import { cn } from "@/lib/utils";

function EmptyState() {
  return (
    <div className="workspace-stage relative flex flex-1 flex-col items-center justify-center gap-4 overflow-hidden px-6 text-center">
      {/* ambient orbs */}
      <span className="orb -left-10 top-[8%] size-56 bg-primary/15 animate-orb-drift" />
      <span className="orb -right-12 bottom-[6%] size-64 bg-orange-400/10 animate-orb-drift [animation-delay:3s]" />

      <span className="rise-stagger stagger-1 relative flex size-14 items-center justify-center rounded-2xl bg-primary/15 text-primary glow-soft animate-float">
        <Sparkles className="size-7" />
      </span>
      <div className="relative">
        <h2 className="rise-stagger stagger-2 text-2xl font-semibold tracking-tight">
          What should <span className="text-gradient">we build?</span>
        </h2>
        <p className="rise-stagger stagger-3 mx-auto mt-2 max-w-md text-sm leading-relaxed text-muted-foreground">
          I have a Linux sandbox with a shell, a filesystem and the internet. Describe the outcome
          and I will plan it, build it, and show you the result as it happens.
        </p>
      </div>
    </div>
  );
}

export function ChatPanel() {
  const messages = useStore((s) => s.messages);
  const running = useStore((s) => s.running);
  const threadId = useStore((s) => s.activeThreadId);

  const scrollRef = useRef<HTMLDivElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const rafRef = useRef<number>(0);
  const [pinned, setPinned] = useState(true);
  const [searchOpen, setSearchOpen] = useState(false);
  const [activeMatch, setActiveMatch] = useState<string | null>(null);
  const outboxCount = useStore((s) => s.outbox.filter((o) => o.threadId === threadId).length);

  useLayoutEffect(() => {
    if (pinned) bottomRef.current?.scrollIntoView({ block: "end" });
  }, [messages, pinned]);

  useEffect(() => {
    setPinned(true);
  }, [threadId]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const tag = document.activeElement?.tagName;
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "f" && tag !== "INPUT" && tag !== "TEXTAREA") {
        event.preventDefault();
        setSearchOpen((v) => !v);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  useEffect(() => () => cancelAnimationFrame(rafRef.current), []);

  // rAF-throttled: scroll fires at 60-120Hz, React only re-renders once per frame.
  const onScroll = () => {
    if (rafRef.current) return;
    rafRef.current = requestAnimationFrame(() => {
      rafRef.current = 0;
      const el = scrollRef.current;
      if (!el) return;
      setPinned(el.scrollHeight - el.scrollTop - el.clientHeight < 120);
    });
  };

  const isEmpty = messages.length === 0;

  return (
    <div className="relative flex h-full flex-col">
      {/* search + outbox overlays */}
      {!isEmpty && (
        <div className="pointer-events-none absolute inset-x-0 top-2 z-10 flex flex-col items-center gap-2">
          {searchOpen ? (
            <div className="pointer-events-auto">
              <ChatSearch onNavigate={setActiveMatch} onClose={() => { setSearchOpen(false); setActiveMatch(null); }} />
            </div>
          ) : (
            <button
              type="button"
              title="Search conversation (Ctrl+F)"
              onClick={() => setSearchOpen(true)}
              className="glass pointer-events-auto rounded-full p-2 text-muted-foreground opacity-50 shadow-md transition-all hover:text-foreground hover:opacity-100"
            >
              <Search className="size-3.5" />
            </button>
          )}
          {outboxCount > 0 ? (
            <span className="glass pointer-events-auto animate-message-in rounded-full px-3 py-1 text-[11px] text-warning">
              {outboxCount} message{outboxCount === 1 ? "" : "s"} queued — will send when back online
            </span>
          ) : null}
        </div>
      )}
      <div ref={scrollRef} onScroll={onScroll} className="scrollbar-thin msg-scroll flex-1 overflow-y-auto">
        {isEmpty ? (
          <div className="flex h-full flex-col">
            <EmptyState />
          </div>
        ) : (
          <div className="mx-auto w-full max-w-3xl px-4 py-6 sm:px-6">
            {messages.map((message) => (
              <div
                key={message.id}
                id={`msg-${message.id}`}
                className={cn("msg-view scroll-mt-16 rounded-xl transition-shadow", activeMatch === message.id && "ring-1 ring-primary shadow-md")}
              >
                <MessageBubble message={message} />
              </div>
            ))}
            <div className="pt-2">
              <PermissionPrompt />
            </div>
            <div ref={bottomRef} className="h-4" />
          </div>
        )}
      </div>

      {!pinned && (
        <Button
          size="icon-sm"
          variant="secondary"
          className="absolute bottom-32 left-1/2 -translate-x-1/2 rounded-full shadow-lg animate-pop-in"
          onClick={() => {
            setPinned(true);
            bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
          }}
        >
          <ArrowDown className="size-4" />
        </Button>
      )}

      <div className="liquid-bar border-t border-border/70 px-4 pb-4 pt-2 sm:px-6">
        <div className="mx-auto w-full max-w-3xl space-y-2">
          <LiveAgentProgress />
          {isEmpty && <PermissionPrompt />}
          <Composer showSuggestions={isEmpty && !running} />
        </div>
      </div>
    </div>
  );
}
