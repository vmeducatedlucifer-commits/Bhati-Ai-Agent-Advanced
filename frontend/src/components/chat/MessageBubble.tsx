import { AlertTriangle, Brain, ChevronRight, GitFork, Pencil, Pin, RotateCcw, Sparkles, User } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Markdown } from "@/components/chat/Markdown";
import { ToolCallCard } from "@/components/chat/ToolCallCard";
import { CopyButton } from "@/components/ui/copy-button";
import { cn } from "@/lib/utils";
import { useStore } from "@/lib/store";
import type { ChatMessage } from "@/types";

/**
 * Thinking indicator — click to expand and see live status (elapsed time,
 * current tool, reasoning so far). Single-motion rule: while THIS animates,
 * the agent avatar stays calm, so exactly one indicator moves at a time.
 */
function ThinkingIndicator({
  toolName,
  reasoning,
}: {
  toolName?: string;
  reasoning?: string;
}) {
  const [open, setOpen] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const startRef = useRef(Date.now());
  useEffect(() => {
    const timer = window.setInterval(
      () => setElapsed(Math.floor((Date.now() - startRef.current) / 1000)),
      1000,
    );
    return () => window.clearInterval(timer);
  }, []);

  return (
    <div className="animate-message-in rounded-xl border border-primary/25 bg-primary/[0.04] py-1.5" aria-label="Agent is thinking">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        title={open ? "Hide live status" : "Show what the agent is doing"}
        className="flex w-full items-center gap-3 px-2 text-left"
      >
        <span className="orbit-wrap relative flex size-8 shrink-0 items-center justify-center" aria-hidden>
          <span className="orbit-core" />
          <span className="orbit-ring orbit-ring-a">
            <span className="orbit-dot" />
          </span>
          <span className="orbit-ring orbit-ring-b">
            <span className="orbit-dot orbit-dot-b" />
          </span>
          <Sparkles className="relative size-3.5 text-primary" />
        </span>
        <span className="min-w-0 flex-1">
          <span className="flex items-center gap-1.5 text-[13.5px] font-medium">
            {toolName ? (
              <>
                Using <span className="truncate font-mono text-primary">{toolName}</span>
                <span className="tdots" aria-hidden>
                  <span className="tdot" />
                  <span className="tdot" />
                  <span className="tdot" />
                </span>
              </>
            ) : (
              <>
                <span className="text-gradient">Thinking</span>
                <span className="tdots" aria-hidden>
                  <span className="tdot" />
                  <span className="tdot" />
                  <span className="tdot" />
                </span>
              </>
            )}
          </span>
          <span className="mt-0.5 block text-[11.5px] tabular-nums text-muted-foreground">
            {elapsed}s{reasoning ? " · reasoning captured" : ""}
          </span>
        </span>
        <ChevronRight className={cn("size-4 shrink-0 text-muted-foreground transition-transform", open && "rotate-90")} />
      </button>
      {open && (
        <div className="animate-fade-in space-y-1.5 border-t border-primary/15 px-3 py-2.5 text-[12.5px]">
          <p className="text-muted-foreground">
            Status:{" "}
            <span className="font-medium text-foreground">
              {toolName ? `running tool ${toolName}` : "waiting for the model"}
            </span>{" "}
            · {elapsed}s elapsed
          </p>
          {reasoning ? (
            <p className="whitespace-pre-wrap italic leading-relaxed text-muted-foreground">{reasoning}</p>
          ) : (
            <p className="italic text-muted-foreground/70">
              {toolName
                ? "Live tool output appears in the tool box below."
                : "First tokens appear here as text as soon as they stream in."}
            </p>
          )}
        </div>
      )}
    </div>
  );
}

function ReasoningBlock({ text }: { text: string }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="rounded-xl border border-border/70 bg-muted/30">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-2 px-3 py-2 text-left text-[13px] text-muted-foreground"
      >
        <Brain className="size-3.5" />
        <span className="flex-1">Thought for a moment</span>
        <ChevronRight className={cn("size-4 transition-transform", open && "rotate-90")} />
      </button>
      {open && (
        <p className="animate-fade-in whitespace-pre-wrap border-t border-border/70 px-3 py-2.5 text-[13px] italic leading-relaxed text-muted-foreground">
          {text}
        </p>
      )}
    </div>
  );
}

function ActionButton({
  title,
  onClick,
  active,
  children,
}: {
  title: string;
  onClick: () => void;
  active?: boolean;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      title={title}
      onClick={(e) => {
        e.stopPropagation();
        onClick();
      }}
      className={cn(
        "rounded-md p-1.5 text-muted-foreground opacity-0 transition-all hover:bg-accent hover:text-foreground group-hover:opacity-100 focus-visible:opacity-100",
        active && "text-primary opacity-100",
      )}
    >
      {children}
    </button>
  );
}

export function MessageBubble({ message }: { message: ChatMessage }) {
  const editResend = useStore((s) => s.editResend);
  const regenerate = useStore((s) => s.regenerate);
  const forkFrom = useStore((s) => s.forkFrom);
  const togglePin = useStore((s) => s.togglePin);
  const pinnedIds = useStore((s) => s.pinnedIds);
  const running = useStore((s) => s.running);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(message.content);
  const pinned = pinnedIds.includes(message.id);

  if (message.role === "user") {
    return (
      <div className="group flex justify-end gap-2.5 sm:gap-3 py-3 max-w-full animate-message-in">
        <div className="max-w-[85%] min-w-0">
          {editing ? (
            <div className="rounded-2xl border border-primary/40 bg-surface p-2 shadow-md animate-scale-in">
              <textarea
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                rows={Math.min(8, draft.split("\n").length + 1)}
                className="w-full resize-y bg-transparent px-2 py-1 text-[14.5px] leading-relaxed focus:outline-none"
                autoFocus
              />
              <div className="flex justify-end gap-1.5 px-1 pb-1">
                <button
                  type="button"
                  onClick={() => {
                    setEditing(false);
                    setDraft(message.content);
                  }}
                  className="rounded-md px-2.5 py-1 text-[12px] text-muted-foreground hover:bg-accent"
                >
                  Cancel
                </button>
                <button
                  type="button"
                  disabled={!draft.trim() || running}
                  onClick={() => {
                    setEditing(false);
                    void editResend(message.id, draft);
                  }}
                  className="rounded-md bg-primary px-2.5 py-1 text-[12px] font-medium text-primary-foreground disabled:opacity-50"
                >
                  Send edited
                </button>
              </div>
            </div>
          ) : (
            <div className="rounded-2xl rounded-br-md bg-secondary px-3.5 sm:px-4 py-2.5 break-words overflow-hidden transition-shadow hover:shadow-md">
              <p className="whitespace-pre-wrap text-[14.5px] sm:text-[15px] leading-relaxed break-words">{message.content}</p>
              {message.attachments?.length ? (
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {message.attachments.map((a) => (
                    <span
                      key={a.path}
                      className="rounded-md bg-background/60 px-1.5 py-0.5 font-mono text-[11px]"
                    >
                      {a.name}
                    </span>
                  ))}
                </div>
              ) : null}
            </div>
          )}
          <div className="mt-1 flex items-center justify-end gap-0.5">
            {message.pending ? (
              <span className="mr-1 text-[10.5px] italic text-muted-foreground">sending…</span>
            ) : null}
            {pinned ? <Pin className="size-3 fill-primary text-primary" /> : null}
            {!message.pending && !editing ? (
              <>
                <ActionButton title="Edit & resend" onClick={() => { setDraft(message.content); setEditing(true); }}>
                  <Pencil className="size-3.5" />
                </ActionButton>
                <ActionButton title="Branch chat from here" onClick={() => void forkFrom(message.id)}>
                  <GitFork className="size-3.5" />
                </ActionButton>
                <ActionButton title={pinned ? "Unpin" : "Pin"} active={pinned} onClick={() => togglePin(message.id)}>
                  <Pin className={cn("size-3.5", pinned && "fill-current")} />
                </ActionButton>
              </>
            ) : null}
          </div>
        </div>
        <span className="mt-1 flex size-7 shrink-0 items-center justify-center rounded-full bg-muted text-muted-foreground">
          <User className="size-3.5" />
        </span>
      </div>
    );
  }

  const empty = !message.content && !message.reasoning && message.tool_calls.length === 0 && !message.error;
  const runningTool = message.streaming
    ? [...message.tool_calls].reverse().find((t) => t.status === "running")?.name
    : undefined;

  return (
    <div className="group flex gap-3 py-3 animate-message-in">
      {/* Single-indicator rule: while the message streams, the ThinkingIndicator
          below carries ALL motion — this avatar stays calm on purpose. */}
      <span className="relative mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-full bg-primary/15 text-primary transition-transform group-hover:scale-105">
        <Sparkles className="size-3.5" />
      </span>

      <div className="min-w-0 flex-1 space-y-3">
        {message.reasoning ? <ReasoningBlock text={message.reasoning} /> : null}

        {message.content ? (
          <div className={cn(message.streaming && "streaming-caret")}>
            <Markdown content={message.content} />
          </div>
        ) : null}

        {!message.streaming && message.content ? (
          <div className="flex items-center gap-0.5 opacity-0 transition-opacity duration-200 group-hover:opacity-100 focus-within:opacity-100">
            <ActionButton title="Regenerate from here" onClick={() => void regenerate(message.id)}>
              <RotateCcw className="size-3.5" />
            </ActionButton>
            <ActionButton title="Branch chat from here" onClick={() => void forkFrom(message.id)}>
              <GitFork className="size-3.5" />
            </ActionButton>
            <ActionButton title={pinned ? "Unpin" : "Pin"} active={pinned} onClick={() => togglePin(message.id)}>
              <Pin className={cn("size-3.5", pinned && "fill-current")} />
            </ActionButton>
            <CopyButton value={message.content} />
          </div>
        ) : null}

        {message.streaming && (!message.content || runningTool) ? (
          <ThinkingIndicator toolName={runningTool} reasoning={message.reasoning} />
        ) : null}

        {message.tool_calls.length > 0 && (
          <div className="space-y-1.5">
            {message.tool_calls.map((call) => (
              <ToolCallCard key={call.id} call={call} />
            ))}
          </div>
        )}

        {message.error ? (
          <div className="flex items-start gap-2 rounded-xl border border-danger/35 bg-danger/5 px-3 py-2.5 text-[13px] text-danger">
            <AlertTriangle className="mt-0.5 size-4 shrink-0" />
            <p className="whitespace-pre-wrap">{message.error}</p>
          </div>
        ) : null}

        {empty && !message.streaming ? (
          <p className="text-[13px] italic text-muted-foreground">(no output)</p>
        ) : null}
      </div>
    </div>
  );
}
