import {
  Archive,
  ChevronRight,
  Download,
  File,
  FileCode,
  FileJson,
  FileText,
  Folder,
  FolderOpen,
  RefreshCw,
  Trash2,
} from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Tooltip } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { useStore } from "@/lib/store";
import { cn, formatBytes } from "@/lib/utils";
import type { FileEntry } from "@/types";

function iconFor(name: string) {
  if (/\.(ts|tsx|js|jsx|py|go|rs|rb|java|c|cpp|sh)$/i.test(name)) return FileCode;
  if (/\.(json|ya?ml|toml)$/i.test(name)) return FileJson;
  if (/\.(md|txt|log)$/i.test(name)) return FileText;
  return File;
}

function Node({
  entry,
  depth,
  threadId,
  onOpen,
  onDeleted,
}: {
  entry: FileEntry;
  depth: number;
  threadId: string;
  onOpen: (path: string) => void;
  onDeleted: () => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const [children, setChildren] = useState<FileEntry[] | null>(null);
  const [loading, setLoading] = useState(false);
  const openFile = useStore((s) => s.openFile);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const result = await api.listFiles(threadId, entry.path);
      setChildren(result.entries);
    } finally {
      setLoading(false);
    }
  }, [threadId, entry.path]);

  const toggle = async () => {
    if (!entry.is_dir) {
      onOpen(entry.path);
      return;
    }
    const next = !expanded;
    setExpanded(next);
    if (next && !children) await load();
  };

  const Icon = entry.is_dir ? (expanded ? FolderOpen : Folder) : iconFor(entry.name);
  const selected = openFile?.path === entry.path;

  return (
    <>
      <div
        className={cn(
          "group flex cursor-pointer items-center gap-1.5 rounded-md py-[3px] pr-1.5 text-[12.5px] transition-colors hover:bg-accent",
          selected && "bg-accent text-foreground",
        )}
        style={{ paddingLeft: `${depth * 12 + 6}px` }}
        onClick={() => void toggle()}
      >
        {entry.is_dir ? (
          <ChevronRight className={cn("size-3 shrink-0 text-muted-foreground transition-transform", expanded && "rotate-90")} />
        ) : (
          <span className="w-3 shrink-0" />
        )}
        <Icon className={cn("size-3.5 shrink-0", entry.is_dir ? "text-primary/70" : "text-muted-foreground")} />
        <span className="truncate">{entry.name}</span>
        {!entry.is_dir && (
          <span className="ml-auto hidden shrink-0 text-[10px] tabular-nums text-muted-foreground group-hover:hidden sm:block">
            {formatBytes(entry.size)}
          </span>
        )}
        <span className="ml-auto hidden items-center gap-0.5 group-hover:flex">
          {!entry.is_dir && (
            <button
              type="button"
              title={`Download ${entry.name}`}
              onClick={(e) => {
                e.stopPropagation();
                void api.downloadFile(threadId, entry.path, entry.name);
              }}
              className="rounded p-0.5 text-muted-foreground hover:text-foreground"
            >
              <Download className="size-3" />
            </button>
          )}
          {entry.is_dir && (
            <button
              type="button"
              title={`Download ${entry.name} as ZIP`}
              onClick={(e) => {
                e.stopPropagation();
                void api.downloadArchive(threadId, entry.path, `${entry.name}.zip`);
              }}
              className="rounded p-0.5 text-muted-foreground hover:text-foreground"
            >
              <Archive className="size-3" />
            </button>
          )}
          <button
            type="button"
            onClick={async (e) => {
              e.stopPropagation();
              if (!confirm(`Delete ${entry.path}?`)) return;
              await api.deleteFile(threadId, entry.path);
              onDeleted();
            }}
            className="rounded p-0.5 text-muted-foreground hover:text-danger"
          >
            <Trash2 className="size-3" />
          </button>
        </span>
      </div>

      {expanded && (
        <div>
          {loading && <p className="py-1 pl-8 text-[11px] text-muted-foreground">Loading…</p>}
          {children?.map((child) => (
            <Node
              key={child.path}
              entry={child}
              depth={depth + 1}
              threadId={threadId}
              onOpen={onOpen}
              onDeleted={() => void load()}
            />
          ))}
          {children?.length === 0 && (
            <p className="py-1 pl-8 text-[11px] text-muted-foreground">empty</p>
          )}
        </div>
      )}
    </>
  );
}

export function FileTree() {
  const threadId = useStore((s) => s.activeThreadId);
  const openPath = useStore((s) => s.openPath);
  const running = useStore((s) => s.running);
  const [entries, setEntries] = useState<FileEntry[]>([]);
  const [loading, setLoading] = useState(false);

  const refresh = useCallback(async () => {
    if (!threadId) return;
    setLoading(true);
    try {
      const result = await api.listFiles(threadId, "");
      setEntries(result.entries);
    } catch {
      setEntries([]);
    } finally {
      setLoading(false);
    }
  }, [threadId]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  // Files change constantly while the agent works; poll gently instead of guessing.
  useEffect(() => {
    if (!running) return;
    const timer = setInterval(() => void refresh(), 4000);
    return () => clearInterval(timer);
  }, [running, refresh]);

  if (!threadId) return null;

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center gap-2 border-b border-border px-3 py-1.5">
        <span className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
          Workspace
        </span>
        <Tooltip content="Refresh">
          <Button variant="ghost" size="icon-sm" className="ml-auto" onClick={() => void refresh()}>
            <RefreshCw className={cn("size-3.5", loading && "animate-spin")} />
          </Button>
        </Tooltip>
      </div>
      <div className="scrollbar-thin min-h-0 flex-1 overflow-y-auto py-1.5 pr-1">
        {entries.length === 0 ? (
          <p className="px-3 py-6 text-center text-[12.5px] text-muted-foreground">
            {loading ? "Loading…" : "Workspace is empty."}
          </p>
        ) : (
          entries.map((entry) => (
            <Node
              key={entry.path}
              entry={entry}
              depth={0}
              threadId={threadId}
              onOpen={(path) => void openPath(path)}
              onDeleted={() => void refresh()}
            />
          ))
        )}
      </div>
    </div>
  );
}
