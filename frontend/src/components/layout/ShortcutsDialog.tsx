import { Keyboard } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

const SHORTCUTS = [
  { key: "⌘B / Ctrl+B", desc: "Toggle Left Sidebar" },
  { key: "⌘K / Ctrl+K", desc: "Start a New Chat" },
  { key: "⌘, / Ctrl+,", desc: "Open Settings Dialog" },
  { key: "/", desc: "Focus Chat Input Box" },
  { key: "Enter", desc: "Send Message in Chat" },
  { key: "Shift + Enter", desc: "Insert Newline in Chat Box" },
  { key: "?", desc: "Show Keyboard Shortcuts Cheatsheet" },
];

export function ShortcutsDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Keyboard className="size-5 text-primary" />
            Keyboard Shortcuts
          </DialogTitle>
          <DialogDescription>
            Quick hotkeys to navigate Rawal AI faster.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-2 pt-2">
          {SHORTCUTS.map((s) => (
            <div
              key={s.key}
              className="flex items-center justify-between rounded-lg border border-border bg-surface px-3 py-2 text-xs"
            >
              <span className="text-muted-foreground">{s.desc}</span>
              <kbd className="rounded bg-muted px-2 py-1 font-mono text-[11px] font-semibold text-foreground">
                {s.key}
              </kbd>
            </div>
          ))}
        </div>
      </DialogContent>
    </Dialog>
  );
}
