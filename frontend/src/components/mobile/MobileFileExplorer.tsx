import { useEffect, useState } from "react";
import {
  ArrowLeft,
  ChevronRight,
  Download,
  FileCode,
  Folder,
  FolderOpen,
  RefreshCw,
  Search,
  Share2,
} from "lucide-react";
import { LightweightEditor } from "@/components/computer/LightweightEditor";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import { hapticLight, hapticMedium } from "@/lib/haptics";
import { useStore } from "@/lib/store";
import type { FileEntry } from "@/types";

export function MobileFileExplorer() {
  const activeThreadId = useStore((s) => s.activeThreadId);
  const openFile = useStore((s) => s.openFile);
  const openPath = useStore((s) => s.openPath);

  const [currentPath, setCurrentPath] = useState("");
  const [entries, setEntries] = useState<FileEntry[]>([]);
  const [searchQuery, setSearchQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const [activeEditingPath, setActiveEditingPath] = useState<string | null>(null);

  const loadDirectory = async (path: string) => {
    if (!activeThreadId) return;
    setLoading(true);
    try {
      const res = await api.listFiles(activeThreadId, path);
      setEntries(res.entries || []);
      setCurrentPath(path);
      setSearchQuery("");
    } catch {
      setEntries([]);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (activeThreadId) {
      void loadDirectory("");
    }
  }, [activeThreadId]);

  const handleSelectEntry = async (entry: FileEntry) => {
    hapticLight();
    if (entry.is_dir) {
      void loadDirectory(entry.path);
    } else {
      await openPath(entry.path);
      setActiveEditingPath(entry.path);
    }
  };

  const handleNavigateUp = () => {
    hapticLight();
    if (!currentPath) return;
    const parts = currentPath.split("/").filter(Boolean);
    parts.pop();
    const parent = parts.join("/");
    void loadDirectory(parent);
  };

  const handleShareFile = async () => {
    if (!openFile) return;
    hapticMedium();
    if (typeof navigator !== "undefined" && navigator.share) {
      try {
        await navigator.share({
          title: openFile.path,
          text: openFile.content,
        });
      } catch {
        /* user cancelled */
      }
    } else {
      void navigator.clipboard.writeText(openFile.content);
    }
  };

  const handleDownloadFile = () => {
    if (!openFile) return;
    hapticMedium();
    const blob = new Blob([openFile.content], { type: "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = openFile.path.split("/").pop() || "file.txt";
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };

  // If viewing/editing a file on mobile
  if (activeEditingPath && openFile) {
    return (
      <div className="flex h-full flex-col pb-16">
        <div className="flex items-center justify-between border-b border-border bg-surface px-2.5 py-1.5 shadow-xs">
          <div className="flex min-w-0 items-center gap-1.5">
            <button
              type="button"
              onClick={() => {
                hapticLight();
                setActiveEditingPath(null);
              }}
              className="flex items-center gap-1 rounded-md px-2 py-1 text-xs font-semibold text-primary active:bg-primary/10"
            >
              <ArrowLeft className="size-4" />
              <span>Back</span>
            </button>
            <span className="truncate font-mono text-xs font-bold text-foreground">{openFile.path}</span>
          </div>
          <div className="flex items-center gap-1">
            <Button
              variant="ghost"
              size="xs"
              onClick={handleShareFile}
              title="Share / Send"
              className="size-7"
            >
              <Share2 className="size-3.5" />
            </Button>
            <Button
              variant="ghost"
              size="xs"
              onClick={handleDownloadFile}
              title="Download to Phone"
              className="size-7"
            >
              <Download className="size-3.5" />
            </Button>
          </div>
        </div>
        <div className="min-h-0 flex-1">
          <LightweightEditor />
        </div>
      </div>
    );
  }

  const filteredEntries = entries.filter((e) =>
    e.name.toLowerCase().includes(searchQuery.toLowerCase()),
  );

  const pathParts = currentPath.split("/").filter(Boolean);

  return (
    <div className="flex h-full flex-col bg-background pb-16">
      {/* Breadcrumb Path Bar */}
      <div className="flex items-center justify-between border-b border-border bg-surface px-3 py-2 shadow-xs">
        <div className="flex items-center gap-1.5 overflow-x-auto text-xs scrollbar-none">
          <button
            type="button"
            onClick={() => {
              hapticLight();
              void loadDirectory("");
            }}
            className="flex items-center gap-1 font-bold text-primary active:scale-95"
          >
            <FolderOpen className="size-4" />
            <span>workspace</span>
          </button>
          {pathParts.map((part, idx) => {
            const sub = pathParts.slice(0, idx + 1).join("/");
            return (
              <div key={sub} className="flex items-center gap-1 shrink-0 text-muted-foreground">
                <ChevronRight className="size-3" />
                <button
                  type="button"
                  onClick={() => {
                    hapticLight();
                    void loadDirectory(sub);
                  }}
                  className="font-mono text-xs font-medium hover:text-foreground active:scale-95"
                >
                  {part}
                </button>
              </div>
            );
          })}
        </div>

        <Button
          variant="ghost"
          size="xs"
          onClick={() => {
            hapticLight();
            void loadDirectory(currentPath);
          }}
          disabled={loading}
          className="size-7 shrink-0"
        >
          <RefreshCw className={`size-3.5 ${loading ? "animate-spin text-primary" : ""}`} />
        </Button>
      </div>

      {/* Search Bar */}
      <div className="border-b border-border/60 bg-muted/20 px-3 py-1.5">
        <div className="flex items-center gap-2 rounded-lg bg-surface px-2.5 py-1 border border-border/60">
          <Search className="size-3.5 text-muted-foreground" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search files in directory..."
            className="flex-1 bg-transparent text-xs outline-hidden placeholder:text-muted-foreground"
          />
        </div>
      </div>

      {/* Directory List */}
      <div className="min-h-0 flex-1 overflow-y-auto divide-y divide-border/40">
        {currentPath && (
          <button
            type="button"
            onClick={handleNavigateUp}
            className="flex w-full items-center gap-3 px-3.5 py-2.5 text-left text-xs text-muted-foreground active:bg-muted/60"
          >
            <ArrowLeft className="size-4 text-primary" />
            <span className="font-semibold">.. (Parent Directory)</span>
          </button>
        )}

        {filteredEntries.length === 0 && !loading && (
          <div className="p-10 text-center text-xs text-muted-foreground">
            <p>No files found.</p>
          </div>
        )}

        {filteredEntries.map((entry) => {
          const Icon = entry.is_dir ? Folder : FileCode;
          return (
            <button
              key={entry.path}
              type="button"
              onClick={() => void handleSelectEntry(entry)}
              className="flex w-full items-center justify-between px-3.5 py-3 text-left text-xs transition active:bg-muted/50"
            >
              <div className="flex min-w-0 items-center gap-3">
                <div
                  className={`flex size-8 shrink-0 items-center justify-center rounded-lg ${
                    entry.is_dir ? "bg-primary/10 text-primary" : "bg-sky-500/10 text-sky-400"
                  }`}
                >
                  <Icon className="size-4.5" />
                </div>
                <div className="min-w-0 flex-1">
                  <span className="block truncate font-mono text-xs font-medium text-foreground">
                    {entry.name}
                  </span>
                  <span className="block text-[10.5px] text-muted-foreground">
                    {entry.is_dir ? "Directory" : entry.size > 1024 ? `${(entry.size / 1024).toFixed(1)} KB` : `${entry.size} bytes`}
                  </span>
                </div>
              </div>
              <ChevronRight className="size-4 text-muted-foreground/40 shrink-0" />
            </button>
          );
        })}
      </div>
    </div>
  );
}
