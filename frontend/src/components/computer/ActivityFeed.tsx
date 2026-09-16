import {
  AlertTriangle,
  BookOpen,
  Bot,
  Brain,
  CircleCheck,
  Info,
  Layers,
  Wrench,
  XCircle,
} from "lucide-react";
import { useEffect, useRef } from "react";
import { PlanPanel } from "@/components/computer/PlanPanel";
import { Spinner } from "@/components/ui/primitives";
import { displayModelName } from "@/lib/api";
import { useStore } from "@/lib/store";
import { cn } from "@/lib/utils";

const KIND_ICON = {
  tool: Wrench,
  thinking: Brain,
  skill: BookOpen,
  subagent: Bot,
  error: XCircle,
  compaction: Layers,
  note: Info,
} as const;

export function ActivityFeed() {
  const activity = useStore((s) => s.activity);
  const runMeta = useStore((s) => s.runMeta);
  const usage = useStore((s) => s.usage);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ block: "end" });
  }, [activity]);

  return (
    <div className="scrollbar-thin h-full space-y-3 overflow-y-auto p-3">
      <PlanPanel />

      {runMeta && (
        <div className="grid grid-cols-2 gap-2 text-[11px]">
          <Stat label="Model" value={runMeta.model ? displayModelName(runMeta.model) : "—"} />
          <Stat label="Sandbox" value={runMeta.sandbox ?? "—"} />
          <Stat label="Tools" value={String(runMeta.tools ?? 0)} />
          <Stat
            label="Tokens"
            value={`${(usage.prompt_tokens + usage.completion_tokens).toLocaleString()}`}
          />
        </div>
      )}

      {activity.length === 0 ? (
        <p className="px-1 py-6 text-center text-[13px] text-muted-foreground">
          Everything the agent does shows up here.
        </p>
      ) : (
        <ol className="relative space-y-0.5 pl-4">
          <span className="absolute bottom-2 left-[7px] top-2 w-px bg-border" aria-hidden />
          {activity.map((item) => {
            const Icon = KIND_ICON[item.kind] ?? Info;
            const running = item.status === "running";
            const failed = item.status === "error";
            return (
              <li key={`${item.id}-${item.at}`} className="relative py-1.5">
                <span
                  className={cn(
                    "absolute -left-4 top-2 flex size-3.5 items-center justify-center rounded-full ring-4 ring-surface",
                    running ? "bg-primary/20" : failed ? "bg-danger/20" : "bg-muted",
                  )}
                >
                  {running ? (
                    <Spinner className="size-2.5 text-primary" />
                  ) : failed ? (
                    <AlertTriangle className="size-2.5 text-danger" />
                  ) : item.kind === "tool" ? (
                    <CircleCheck className="size-2.5 text-emerald-500" />
                  ) : (
                    <Icon className="size-2.5 text-muted-foreground" />
                  )}
                </span>
                <p className="font-mono text-[12.5px]">{item.title}</p>
                {item.detail ? (
                  <p className="line-clamp-3 text-[11.5px] text-muted-foreground">{item.detail}</p>
                ) : null}
              </li>
            );
          })}
          <div ref={bottomRef} />
        </ol>
      )}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-border bg-surface px-2.5 py-1.5">
      <p className="text-[10px] uppercase tracking-wide text-muted-foreground">{label}</p>
      <p className="truncate font-mono text-[12px]">{value}</p>
    </div>
  );
}
