import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Field, Input } from "@/components/ui/input";
import { useStore } from "@/lib/store";

export function NewProjectDialog({
  open,
  onOpenChange,
  initialName = "",
  initialDescription = "",
}: {
  open: boolean;
  onOpenChange: (value: boolean) => void;
  initialName?: string;
  initialDescription?: string;
}) {
  const createProject = useStore((s) => s.createProject);
  const [name, setName] = useState(initialName);
  const [description, setDescription] = useState(initialDescription);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (open) {
      setName(initialName);
      setDescription(initialDescription);
    }
  }, [open, initialName, initialDescription]);

  const submit = async () => {
    if (!name.trim()) return;
    setBusy(true);
    try {
      await createProject(name.trim(), description.trim());
      setName("");
      setDescription("");
      onOpenChange(false);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>New project</DialogTitle>
          <DialogDescription>
            A project owns a workspace directory. Every chat inside it gets its own sandbox mounted
            on that directory, so files persist across conversations.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-3">
          <div className="rounded-xl border border-primary/20 bg-primary/5 px-3 py-2 text-xs leading-relaxed text-muted-foreground">
            Start from a focused workflow, or describe your own project. The agent can research,
            plan, build, test, and ship from the same workspace.
          </div>
          <Field label="Name">
            <Input
              autoFocus
              value={name}
              placeholder="my-saas-app"
              onChange={(e) => setName(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && void submit()}
            />
          </Field>
          <Field label="Description" hint="Optional.">
            <Input
              value={description}
              placeholder="Next.js storefront with Stripe checkout"
              onChange={(e) => setDescription(e.target.value)}
            />
          </Field>
        </div>

        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button disabled={!name.trim() || busy} onClick={() => void submit()}>
            Create project
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
