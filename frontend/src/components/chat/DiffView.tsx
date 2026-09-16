import { useMemo } from "react";
import { cn } from "@/lib/utils";

/** Renders a unified diff with per-line colouring, Claude Code style. */
export function DiffView({ diff, className }: { diff: string; className?: string }) {
  const lines = useMemo(() => diff.split("\n"), [diff]);
  const stats = useMemo(() => {
    let added = 0;
    let removed = 0;
    for (const line of lines) {
      if (line.startsWith("+") && !line.startsWith("+++")) added += 1;
      else if (line.startsWith("-") && !line.startsWith("---")) removed += 1;
    }
    return { added, removed };
  }, [lines]);

  if (!diff.trim()) {
    return <p className="px-3 py-2 text-xs text-muted-foreground">No changes.</p>;
  }

  return (
    <div className={cn("overflow-hidden rounded-lg border border-border bg-surface", className)}>
      <div className="flex items-center gap-3 border-b border-border px-3 py-1.5 text-[11px]">
        <span className="text-emerald-600 dark:text-emerald-400">+{stats.added}</span>
        <span className="text-rose-600 dark:text-rose-400">−{stats.removed}</span>
      </div>
      <div className="scrollbar-thin max-h-[420px] overflow-auto">
        <pre className="font-mono text-[12.5px] leading-[1.55]">
          {lines.map((line, index) => {
            const isAdd = line.startsWith("+") && !line.startsWith("+++");
            const isDel = line.startsWith("-") && !line.startsWith("---");
            const isHunk = line.startsWith("@@");
            const isMeta = line.startsWith("+++") || line.startsWith("---") || line.startsWith("diff ");
            return (
              <div
                key={index}
                className={cn(
                  "px-3",
                  isAdd && "diff-line-add",
                  isDel && "diff-line-del",
                  isHunk && "diff-line-hunk",
                  isMeta && "text-muted-foreground",
                )}
              >
                {line || " "}
              </div>
            );
          })}
        </pre>
      </div>
    </div>
  );
}
