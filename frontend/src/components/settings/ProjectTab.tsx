import { Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Field } from "@/components/ui/input";
import { Badge } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { activeProject, useStore } from "@/lib/store";
import { relativeTime } from "@/lib/utils";

export function ProjectTab() {
  const project = useStore(activeProject);
  const [instructions, setInstructions] = useState(project?.instructions ?? "");
  const [memories, setMemories] = useState<{ id: string; key: string; value: string; updated_at: string }[]>([]);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    setInstructions(project?.instructions ?? "");
    if (project) void api.listMemories(project.id).then(setMemories);
  }, [project]);

  if (!project) {
    return <p className="text-[13px] text-muted-foreground">Create a project first.</p>;
  }

  return (
    <div className="space-y-5">
      <div className="rounded-xl border border-border bg-surface p-3">
        <p className="text-[13px] font-medium">{project.name}</p>
        <p className="truncate font-mono text-[11.5px] text-muted-foreground">{project.workspace_path}</p>
      </div>

      <Field
        label="Project instructions"
        hint="Prepended to the system prompt for every chat in this project — conventions, stack, do-nots."
      >
        <textarea
          value={instructions}
          onChange={(e) => {
            setInstructions(e.target.value);
            setSaved(false);
          }}
          rows={6}
          placeholder={"Use pnpm, not npm.\nTests live next to the file they cover.\nNever touch infra/ without asking."}
          className="w-full rounded-lg border border-input bg-surface px-3 py-2 text-[13px] leading-relaxed"
        />
      </Field>
      <div className="flex items-center gap-2">
        <Button
          size="sm"
          onClick={async () => {
            await api.updateProject(project.id, { instructions });
            setSaved(true);
          }}
        >
          Save instructions
        </Button>
        {saved ? <span className="text-[12.5px] text-emerald-500">Saved</span> : null}
      </div>

      <div>
        <p className="mb-2 text-[13px] font-medium">
          Agent memory{" "}
          <Badge tone="muted" className="ml-1">
            {memories.length}
          </Badge>
        </p>
        <p className="mb-2 text-[12px] text-muted-foreground">
          Facts the agent chose to remember about this project. Delete anything that went stale.
        </p>
        {memories.length === 0 ? (
          <p className="text-[12.5px] text-muted-foreground">Nothing remembered yet.</p>
        ) : (
          <ul className="space-y-1.5">
            {memories.map((memory) => (
              <li
                key={memory.id}
                className="flex items-start gap-2 rounded-lg border border-border bg-surface px-3 py-2"
              >
                <div className="min-w-0 flex-1">
                  <p className="font-mono text-[12px] text-primary">{memory.key}</p>
                  <p className="text-[12.5px]">{memory.value}</p>
                  <p className="text-[10.5px] text-muted-foreground">{relativeTime(memory.updated_at)}</p>
                </div>
                <Button
                  variant="ghost"
                  size="icon-sm"
                  onClick={async () => {
                    await api.deleteMemory(project.id, memory.id);
                    setMemories((prev) => prev.filter((m) => m.id !== memory.id));
                  }}
                >
                  <Trash2 className="size-3.5 text-danger" />
                </Button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
