import { Check, CircleCheck, CircleDashed, CircleDot, ClipboardList, TriangleAlert } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Markdown } from "@/components/chat/Markdown";
import { Spinner } from "@/components/ui/primitives";
import { useStore } from "@/lib/store";
import { cn } from "@/lib/utils";

const ICON = {
  completed: CircleCheck,
  in_progress: CircleDot,
  pending: CircleDashed,
  blocked: TriangleAlert,
} as const;

export function PlanPanel({ compact = false }: { compact?: boolean }) {
  const todos = useStore((s) => s.todos);
  const planContent = useStore((s) => s.planContent);
  const setThreadMode = useStore((s) => s.setThreadMode);
  const send = useStore((s) => s.send);
  const running = useStore((s) => s.running);
  const setDraft = useStore((s) => s.setDraft);

  if (planContent) {
    return (
      <div className={cn("gradient-border rounded-xl bg-surface animate-message-in", compact ? "p-2.5" : "p-3.5")}>
        <p className="mb-2 flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wide text-primary">
          <ClipboardList className="size-3.5" />
          Plan awaiting approval
        </p>
        <div className="scrollbar-thin max-h-64 overflow-y-auto rounded-lg bg-muted/30 p-2.5">
          <Markdown content={planContent} />
        </div>
        <div className="mt-2.5 flex gap-1.5">
          <Button
            size="sm"
            disabled={running}
            onClick={() => void setThreadMode("agent").then(() => send("Plan approved — execute it step by step."))}
            className="glow-soft"
          >
            <Check className="size-3.5" />
            Approve & execute
          </Button>
          <Button
            size="sm"
            variant="outline"
            onClick={() => setDraft("Please revise the plan: ")}
          >
            Request changes
          </Button>
        </div>
      </div>
    );
  }

  if (todos.length === 0) return null;

  const done = todos.filter((t) => t.status === "completed").length;
  const progress = Math.round((done / todos.length) * 100);

  return (
    <div className={cn("rounded-xl border border-border bg-surface", compact ? "p-2.5" : "p-3.5")}>
      <div className="mb-2 flex items-center justify-between">
        <p className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">Plan</p>
        <span className="text-[11px] tabular-nums text-muted-foreground">
          {done}/{todos.length}
        </span>
      </div>

      <div className="mb-3 h-1 overflow-hidden rounded-full bg-muted">
        <div
          className="h-full rounded-full bg-primary transition-all duration-500"
          style={{ width: `${progress}%` }}
        />
      </div>

      <ul className="space-y-1.5">
        {todos.map((todo) => {
          const Icon = ICON[todo.status] ?? CircleDashed;
          const active = todo.status === "in_progress";
          return (
            <li key={todo.id} className="flex items-start gap-2 text-[13px]">
              {active ? (
                <Spinner className="mt-0.5 size-3.5 shrink-0 text-primary" />
              ) : (
                <Icon
                  className={cn(
                    "mt-0.5 size-3.5 shrink-0",
                    todo.status === "completed" && "text-emerald-500",
                    todo.status === "blocked" && "text-amber-500",
                    todo.status === "pending" && "text-muted-foreground/50",
                  )}
                />
              )}
              <span className="min-w-0 flex-1">
                <span
                  className={cn(
                    todo.status === "completed" && "text-muted-foreground line-through",
                    active && "font-medium",
                  )}
                >
                  {todo.title}
                </span>
                {todo.note ? (
                  <span className="block text-[11px] text-muted-foreground">{todo.note}</span>
                ) : null}
              </span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
