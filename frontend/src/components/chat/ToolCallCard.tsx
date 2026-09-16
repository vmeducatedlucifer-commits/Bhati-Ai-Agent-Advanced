import {
  AlertTriangle,
  Bot,
  Braces,
  ChevronRight,
  CircleCheck,
  FileCode,
  FilePen,
  FilePlus,
  FileText,
  FolderTree,
  Github,
  Globe,
  ListChecks,
  Lightbulb,
  Package,
  Rocket,
  Search,
  ShieldOff,
  Terminal,
  Trash2,
  GitBranch,
  Brain,
} from "lucide-react";
import { useState } from "react";
import { DiffView } from "@/components/chat/DiffView";
import { Badge, Spinner } from "@/components/ui/primitives";
import { CopyButton } from "@/components/ui/copy-button";
import { useStore } from "@/lib/store";
import { cn, formatDuration, truncateMiddle } from "@/lib/utils";
import type { ToolCall } from "@/types";

const ICONS: Record<string, typeof FileText> = {
  read_file: FileText,
  write_file: FilePlus,
  edit_file: FilePen,
  list_files: FolderTree,
  delete_file: Trash2,
  glob: Search,
  grep: Search,
  bash: Terminal,
  bash_output: Terminal,
  install_packages: Package,
  web_search: Globe,
  web_fetch: Globe,
  todo_write: ListChecks,
  think: Lightbulb,
  task: Bot,
  create_artifact: FileCode,
  remember: Brain,
  recall: Brain,
  github: Github,
  github_push: Github,
  vercel: Rocket,
  render: Rocket,
  huggingface: Rocket,
  start_server: Rocket,
  stop_server: Rocket,
  open_in_browser: Globe,
  git_status: GitBranch,
  git_diff: GitBranch,
  git_commit: GitBranch,
  git_log: GitBranch,
  git_branch: GitBranch,
  git_clone: GitBranch,
  notebook_edit: FileCode,
  question: Lightbulb,
  worktree_enter: GitBranch,
  worktree_exit: GitBranch,
  code_review: Search,
  commit_push_pr: Rocket,
  clean_gone_branches: Trash2,
  synthetic_output: Braces,
};

/** One-line summary shown on the collapsed card. */
function summarise(call: ToolCall): string {
  const a = call.arguments ?? {};
  const pick = (key: string) => (typeof a[key] === "string" ? (a[key] as string) : "");
  switch (call.name) {
    case "notebook_edit":
      return `${pick("action")} cell in ${pick("notebook_path")}`;
    case "question":
      return "Asking user choice";
    case "worktree_enter":
      return `worktree: ${pick("branch_name")}`;
    case "worktree_exit":
      return `exit worktree: ${pick("path")}`;
    case "code_review":
      return "Running multi-agent code review";
    case "commit_push_pr":
      return `PR: ${pick("commit_message")}`;
    case "clean_gone_branches":
      return "Pruning merged git branches";
    case "synthetic_output":
      return "Structured JSON output";
    case "read_file":
    case "write_file":
    case "edit_file":
    case "delete_file":
      return truncateMiddle(pick("path"), 56);
    case "list_files":
      return pick("path") || ".";
    case "glob":
      return pick("pattern");
    case "grep":
      return `"${pick("pattern")}"${pick("glob_filter") ? ` in ${pick("glob_filter")}` : ""}`;
    case "bash":
    case "bash_output":
      return truncateMiddle(pick("command"), 72);
    case "install_packages":
      return `${pick("manager")} ${pick("packages")}`;
    case "web_search":
      return pick("query");
    case "web_fetch":
    case "open_in_browser":
      return truncateMiddle(pick("url"), 56);
    case "task":
      return `${pick("agent_type")} · ${pick("description")}`;
    case "todo_write":
      return `${(a.todos as unknown[] | undefined)?.length ?? 0} steps`;
    case "think":
      return truncateMiddle(pick("thought"), 72);
    case "create_artifact":
      return pick("title");
    case "remember":
      return pick("key");
    case "start_server":
      return `port ${String(a.port ?? "")}`;
    case "github_push":
      return pick("repo");
    default:
      if (call.name.startsWith("mcp__")) return call.name.split("__").slice(2).join("__");
      return Object.values(a)
        .filter((v) => typeof v === "string")
        .map((v) => truncateMiddle(String(v), 40))
        .join(" ")
        .slice(0, 72);
  }
}

function VERB(name: string): string {
  const verbs: Record<string, string> = {
    read_file: "Read",
    write_file: "Wrote",
    edit_file: "Edited",
    delete_file: "Deleted",
    list_files: "Listed",
    glob: "Found files",
    grep: "Searched",
    bash: "Ran",
    bash_output: "Checked",
    install_packages: "Installed",
    web_search: "Searched web",
    web_fetch: "Fetched",
    todo_write: "Planned",
    think: "Thought",
    task: "Delegated",
    create_artifact: "Published",
    remember: "Remembered",
    recall: "Recalled",
    start_server: "Started server",
    stop_server: "Stopped server",
    open_in_browser: "Opened",
    github_push: "Pushed",
  };
  if (verbs[name]) return verbs[name];
  if (name.startsWith("mcp__")) return `MCP ${name.split("__")[1]}`;
  if (name.startsWith("git_")) return `git ${name.slice(4)}`;
  return name;
}

export function ToolCallCard({ call }: { call: ToolCall }) {
  // Running tools start expanded so live work is visible; the user can
  // collapse anytime. Finished cards keep whatever state they had.
  const [open, setOpen] = useState(call.status === "running");
  const openPath = useStore((s) => s.openPath);
  const navigateBrowser = useStore((s) => s.navigateBrowser);

  const Icon = ICONS[call.name] ?? Braces;
  const display = call.display as Record<string, unknown> | null | undefined;
  const running = call.status === "running";
  const failed = call.status === "error";
  const denied = call.status === "denied";

  return (
    <div
      className={cn(
        "group rounded-xl border bg-surface/60 transition-colors",
        failed ? "border-danger/35" : denied ? "border-amber-500/35" : "border-border",
      )}
    >
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-2.5 px-3 py-2 text-left"
      >
        <span
          className={cn(
            "flex size-6 shrink-0 items-center justify-center rounded-md",
            running ? "bg-primary/15 text-primary" : failed ? "bg-danger/15 text-danger" : "bg-muted text-muted-foreground",
          )}
        >
          {running ? <Spinner className="size-3.5" /> : <Icon className="size-3.5" />}
        </span>

        <span className="min-w-0 flex-1">
          <span className="text-[13px] font-medium">{VERB(call.name)}</span>{" "}
          <span className="truncate font-mono text-[12.5px] text-muted-foreground">{summarise(call)}</span>
        </span>

        {denied && (
          <Badge tone="warning">
            <ShieldOff className="size-3" /> denied
          </Badge>
        )}
        {failed && (
          <Badge tone="danger">
            <AlertTriangle className="size-3" /> failed
          </Badge>
        )}
        {!running && !failed && !denied && call.duration_ms ? (
          <span className="text-[11px] tabular-nums text-muted-foreground/70">
            {formatDuration(call.duration_ms)}
          </span>
        ) : null}

        <ChevronRight
          className={cn("size-4 shrink-0 text-muted-foreground transition-transform", open && "rotate-90")}
        />
      </button>

      {open && (
        <div className="animate-fade-in space-y-3 border-t border-border px-3 py-3">
          {Object.keys(call.arguments ?? {}).length > 0 && (
            <details className="text-xs" open={!display}>
              <summary className="cursor-pointer select-none text-muted-foreground">Arguments</summary>
              <pre className="scrollbar-thin mt-2 max-h-52 overflow-auto rounded-lg bg-muted/60 p-2.5 font-mono text-[12px] break-all max-w-full">
                {JSON.stringify(call.arguments, null, 2)}
              </pre>
            </details>
          )}

          <ToolDisplay call={call} onOpenPath={openPath} onNavigate={navigateBrowser} />

          {call.result && !display && (
            <div className="relative">
              <CopyButton value={call.result} className="absolute right-1 top-1" />
              <pre className="scrollbar-thin max-h-80 overflow-auto whitespace-pre-wrap rounded-lg bg-muted/50 p-2.5 font-mono text-[12px] leading-relaxed break-all max-w-full">
                {call.result}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function ToolDisplay({
  call,
  onOpenPath,
  onNavigate,
}: {
  call: ToolCall;
  onOpenPath: (path: string) => void;
  onNavigate: (url: string) => void;
}) {
  const display = call.display as Record<string, unknown> | null | undefined;
  if (!display) return null;

  switch (display.kind) {
    case "diff":
      return (
        <div className="space-y-1.5">
          <button
            type="button"
            onClick={() => onOpenPath(String(display.path))}
            className="font-mono text-xs text-primary hover:underline break-all"
          >
            {String(display.path)}
          </button>
          <DiffView diff={String(display.diff ?? "")} />
        </div>
      );

    case "file":
      return (
        <div className="space-y-1.5">
          <button
            type="button"
            onClick={() => onOpenPath(String(display.path))}
            className="font-mono text-xs text-primary hover:underline break-all"
          >
            Open {String(display.path)} in editor
          </button>
          <pre className="scrollbar-thin max-h-72 overflow-auto rounded-lg bg-muted/50 p-2.5 font-mono text-[12px] max-w-full break-all whitespace-pre-wrap">
            {String(display.content ?? "").slice(0, 8000)}
          </pre>
        </div>
      );

    case "terminal":
      return (
        <div className="overflow-hidden rounded-lg border border-border bg-[#0d1117] max-w-full">
          <div className="border-b border-white/10 px-3 py-1.5 font-mono text-[11.5px] text-emerald-400 break-all">
            $ {String(display.command ?? "")}
          </div>
          <pre className="scrollbar-thin max-h-80 overflow-auto p-3 font-mono text-[12px] leading-relaxed text-zinc-300 max-w-full break-all whitespace-pre-wrap">
            {String(display.output ?? "").slice(-20000) || "(no output)"}
          </pre>
        </div>
      );

    case "search":
      return (
        <ul className="space-y-2">
          {((display.results as { title: string; url: string; snippet: string }[]) ?? []).map((r) => (
            <li key={r.url} className="rounded-lg border border-border p-2.5 max-w-full overflow-hidden">
              <a
                href={r.url}
                target="_blank"
                rel="noreferrer"
                className="text-[13px] font-medium text-primary hover:underline"
              >
                {r.title || r.url}
              </a>
              <p className="mt-0.5 truncate text-[11px] text-muted-foreground break-all">{r.url}</p>
              {r.snippet ? <p className="mt-1 text-xs text-muted-foreground">{r.snippet}</p> : null}
            </li>
          ))}
        </ul>
      );

    case "list":
    case "tree": {
      const items =
        (display.items as string[]) ??
        ((display.entries as { name: string; path: string; is_dir: boolean }[]) ?? []).map(
          (e) => `${e.is_dir ? "📁" : "📄"} ${e.name}`,
        );
      return (
        <pre className="scrollbar-thin max-h-72 overflow-auto rounded-lg bg-muted/50 p-2.5 font-mono text-[12px] max-w-full break-all whitespace-pre-wrap">
          {items.join("\n") || "(empty)"}
        </pre>
      );
    }

    case "todos":
      return (
        <ul className="space-y-1 text-[13px]">
          {((display.todos as { id: string; title: string; status: string }[]) ?? []).map((t) => (
            <li key={t.id} className="flex items-center gap-2">
              {t.status === "completed" ? (
                <CircleCheck className="size-3.5 text-emerald-500" />
              ) : t.status === "in_progress" ? (
                <Spinner className="size-3.5 text-primary" />
              ) : (
                <span className="size-3.5 rounded-full border border-muted-foreground/40" />
              )}
              <span className={cn(t.status === "completed" && "text-muted-foreground line-through")}>
                {t.title}
              </span>
            </li>
          ))}
        </ul>
      );

    case "thinking":
      return (
        <p className="whitespace-pre-wrap rounded-lg border-l-2 border-primary/40 bg-muted/40 p-2.5 text-[13px] italic text-muted-foreground">
          {String(display.text ?? "")}
        </p>
      );

    case "subagent":
      return (
        <div className="rounded-lg border border-border bg-muted/40 p-2.5">
          <p className="mb-1.5 text-[11px] uppercase tracking-wide text-muted-foreground">
            {String(display.agent_type)} · {String(display.description)}
          </p>
          <p className="whitespace-pre-wrap text-[13px]">{String(display.report ?? "")}</p>
        </div>
      );

    case "preview":
    case "browser":
      return (
        <button
          type="button"
          onClick={() => onNavigate(String(display.url))}
          className="text-[13px] text-primary hover:underline"
        >
          Open {String(display.url)} in the Browser tab
        </button>
      );

    case "link":
      return (
        <a
          href={String(display.url)}
          target="_blank"
          rel="noreferrer"
          className="text-[13px] text-primary hover:underline"
        >
          {String(display.label ?? display.url)}
        </a>
      );

    case "artifact":
      return (
        <div className="rounded-lg border border-primary/30 bg-primary/5 p-2.5">
          <p className="text-[13px] font-medium">{String(display.title)}</p>
          <p className="text-[11px] text-muted-foreground">{String(display.artifact_kind)}</p>
        </div>
      );

    default:
      return null;
  }
}
