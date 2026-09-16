import { ChevronDown, ChevronUp, Pin, Search, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useStore } from "@/lib/store";
import { cn } from "@/lib/utils";

export function ChatSearch({
  onNavigate,
  onClose,
}: {
  onNavigate: (messageId: string | null) => void;
  onClose: () => void;
}) {
  const messages = useStore((s) => s.messages);
  const pinnedIds = useStore((s) => s.pinnedIds);
  const [query, setQuery] = useState("");
  const [index, setIndex] = useState(0);
  const [pinnedOnly, setPinnedOnly] = useState(false);

  const matches = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return messages.filter((m) => {
      if (pinnedOnly && !pinnedIds.includes(m.id)) return false;
      if (!needle) return pinnedOnly;
      return m.content.toLowerCase().includes(needle);
    });
  }, [messages, query, pinnedOnly, pinnedIds]);

  useEffect(() => {
    setIndex(0);
  }, [query, pinnedOnly, messages.length]);

  useEffect(() => {
    const target = matches[Math.min(index, matches.length - 1)];
    if (target) {
      onNavigate(target.id);
      requestAnimationFrame(() => {
        document.getElementById(`msg-${target.id}`)?.scrollIntoView({ block: "center", behavior: "smooth" });
      });
    } else {
      onNavigate(null);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [index, matches.length]);

  const step = (delta: number) => {
    if (!matches.length) return;
    setIndex((i) => (i + delta + matches.length) % matches.length);
  };

  return (
    <div className="glass animate-scale-in flex items-center gap-1.5 rounded-xl px-2.5 py-1.5 shadow-lg">
      <Search className="size-3.5 shrink-0 text-muted-foreground" />
      <input
        autoFocus
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter") step(e.shiftKey ? -1 : 1);
          if (e.key === "Escape") onClose();
        }}
        placeholder="Search conversation…"
        className="w-36 bg-transparent text-[13px] focus:outline-none sm:w-48"
      />
      <button
        type="button"
        title="Pinned only"
        onClick={() => setPinnedOnly((v) => !v)}
        className={cn(
          "rounded p-1 text-muted-foreground hover:text-foreground",
          pinnedOnly && "bg-primary/15 text-primary",
        )}
      >
        <Pin className="size-3.5" />
      </button>
      <span className="min-w-10 text-center text-[11px] tabular-nums text-muted-foreground">
        {matches.length ? `${Math.min(index + 1, matches.length)}/${matches.length}` : "0/0"}
      </span>
      <button type="button" onClick={() => step(-1)} className="rounded p-1 text-muted-foreground hover:text-foreground">
        <ChevronUp className="size-3.5" />
      </button>
      <button type="button" onClick={() => step(1)} className="rounded p-1 text-muted-foreground hover:text-foreground">
        <ChevronDown className="size-3.5" />
      </button>
      <button type="button" onClick={onClose} className="rounded p-1 text-muted-foreground hover:text-foreground">
        <X className="size-3.5" />
      </button>
    </div>
  );
}
