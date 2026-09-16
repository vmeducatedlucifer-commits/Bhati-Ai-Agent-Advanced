import { Download, FileCode, FileText, Image, MessageSquare, Package, Send } from "lucide-react";
import { useEffect, useState } from "react";
import { Markdown } from "@/components/chat/Markdown";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import { useStore } from "@/lib/store";
import { cn, formatBytes, relativeTime } from "@/lib/utils";
import type { Artifact } from "@/types";

const ICONS: Record<string, typeof FileText> = {
  markdown: FileText,
  html: FileCode,
  code: FileCode,
  image: Image,
  file: Package,
};

export function ArtifactsView() {
  const artifacts = useStore((s) => s.artifacts);
  const threadId = useStore((s) => s.activeThreadId);
  const [selected, setSelected] = useState<Artifact | null>(null);

  if (artifacts.length === 0) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-2 text-center text-muted-foreground">
        <Package className="size-8 opacity-40" />
        <p className="max-w-xs text-[13px]">
          Finished deliverables the agent publishes (reports, pages, exports) land here.
        </p>
      </div>
    );
  }

  const current = selected ?? artifacts[0];
  const Icon = ICONS[current.kind] ?? Package;
  const [comments, setComments] = useState<{ id: string; author: string; content: string; created_at: string }[]>([]);
  const [commentDraft, setCommentDraft] = useState("");

  useEffect(() => {
    if (!threadId) return;
    setComments([]);
    setCommentDraft("");
    void api.listComments(threadId, current.id).then(setComments).catch(() => setComments([]));
  }, [threadId, current.id]);

  return (
    <div className="flex h-full">
      <div className="scrollbar-thin w-48 shrink-0 overflow-y-auto border-r border-border py-1.5">
        {artifacts.map((artifact) => {
          const ItemIcon = ICONS[artifact.kind] ?? Package;
          return (
            <button
              key={artifact.id}
              type="button"
              onClick={() => setSelected(artifact)}
              className={cn(
                "flex w-full items-start gap-2 px-2.5 py-1.5 text-left text-[12.5px] transition-colors hover:bg-accent",
                current.id === artifact.id && "bg-accent",
              )}
            >
              <ItemIcon className="mt-0.5 size-3.5 shrink-0 text-primary/70" />
              <span className="min-w-0 flex-1">
                <span className="block truncate">{artifact.title}</span>
                <span className="block text-[10.5px] text-muted-foreground">
                  {formatBytes(artifact.size)} · {relativeTime(artifact.created_at)}
                </span>
              </span>
            </button>
          );
        })}
      </div>

      <div className="flex min-w-0 flex-1 flex-col">
        <div className="flex items-center gap-2 border-b border-border px-3 py-1.5">
          <Icon className="size-3.5 text-primary" />
          <span className="truncate text-[12.5px] font-medium">{current.title}</span>
          {current.path && threadId ? (
            <Button
              variant="ghost"
              size="xs"
              className="ml-auto"
              onClick={() => void api.downloadFile(threadId, current.path, current.title)}
            >
              <Download className="size-3.5" />
              Download
            </Button>
          ) : null}
        </div>

        <div className="scrollbar-thin min-h-0 flex-1 overflow-auto p-4">
          {current.kind === "markdown" ? (
            <Markdown content={current.content} />
          ) : current.kind === "html" ? (
            <iframe
              srcDoc={current.content}
              title={current.title}
              className="h-full min-h-[420px] w-full rounded-lg border border-border bg-white"
              sandbox="allow-scripts"
            />
          ) : (
            <pre className="whitespace-pre-wrap font-mono text-[12.5px]">{current.content}</pre>
          )}

          {/* comments */}
          <div className="mt-4 border-t border-border pt-3">
            <p className="mb-2 flex items-center gap-1.5 text-[12px] font-medium">
              <MessageSquare className="size-3.5 text-primary" />
              Comments ({comments.length})
            </p>
            <ul className="mb-2 space-y-1.5">
              {comments.map((c) => (
                <li key={c.id} className="rounded-lg bg-muted/40 px-2.5 py-1.5">
                  <p className="text-[10.5px] font-medium text-muted-foreground">
                    {c.author} · {relativeTime(c.created_at)}
                  </p>
                  <p className="whitespace-pre-wrap text-[12.5px]">{c.content}</p>
                </li>
              ))}
            </ul>
            {threadId ? (
              <div className="flex gap-1.5">
                <input
                  value={commentDraft}
                  onChange={(e) => setCommentDraft(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && commentDraft.trim()) {
                      const text = commentDraft.trim();
                      setCommentDraft("");
                      void api.addComment(threadId, current.id, text).then((c) =>
                        setComments((prev) => [...prev, { ...c, created_at: new Date().toISOString() }]),
                      );
                    }
                  }}
                  placeholder="Comment on this artifact…"
                  className="h-8 flex-1 rounded-lg border border-input bg-surface px-2.5 text-[12px] focus:outline-none"
                />
                <Button
                  size="icon-sm"
                  variant="ghost"
                  disabled={!commentDraft.trim()}
                  onClick={() => {
                    const text = commentDraft.trim();
                    setCommentDraft("");
                    void api.addComment(threadId, current.id, text).then((c) =>
                      setComments((prev) => [...prev, { ...c, created_at: new Date().toISOString() }]),
                    );
                  }}
                >
                  <Send className="size-3.5" />
                </Button>
              </div>
            ) : null}
          </div>
        </div>
      </div>
    </div>
  );
}
