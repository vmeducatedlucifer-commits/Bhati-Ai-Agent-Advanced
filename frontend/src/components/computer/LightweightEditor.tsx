import { useEffect, useRef } from "react";
import { Copy, Save } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/primitives";
import { useStore } from "@/lib/store";

interface LightweightEditorProps {
  filePath?: string;
  content?: string;
  onChange?: (val: string) => void;
  onSave?: () => void;
  readOnly?: boolean;
}

export function LightweightEditor({
  filePath,
  content,
  onChange,
  onSave,
  readOnly = false,
}: LightweightEditorProps) {
  const openFile = useStore((s) => s.openFile);
  const save = useStore((s) => s.saveOpenFile);
  const setContent = useStore((s) => s.setOpenFileContent);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const activePath = filePath || openFile?.path || "untitled.txt";
  const activeContent = content !== undefined ? content : openFile?.content || "";
  const isDirty = openFile?.dirty ?? false;

  const handleSave = () => {
    if (onSave) onSave();
    else void save();
  };

  const handleChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    const val = e.target.value;
    if (onChange) onChange(val);
    else setContent(val);
  };

  // Keyboard shortcut Ctrl+S
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "s") {
        e.preventDefault();
        handleSave();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  // Handle Tab key for indentation
  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Tab") {
      e.preventDefault();
      const ta = e.currentTarget;
      const start = ta.selectionStart;
      const end = ta.selectionEnd;
      const val = ta.value;
      const newVal = val.substring(0, start) + "  " + val.substring(end);
      if (onChange) onChange(newVal);
      else setContent(newVal);
      setTimeout(() => {
        ta.selectionStart = ta.selectionEnd = start + 2;
      }, 0);
    }
  };

  const lineCount = activeContent.split("\n").length;

  return (
    <div className="flex h-full flex-col bg-background font-mono text-[12.5px]">
      {/* Editor Header */}
      <div className="flex items-center justify-between border-b border-border bg-surface px-3 py-1.5">
        <div className="flex items-center gap-2 overflow-hidden">
          <span className="truncate font-semibold text-foreground">{activePath}</span>
          {isDirty && !readOnly && <Badge tone="warning">unsaved</Badge>}
          <span className="text-[11px] text-muted-foreground">{lineCount} lines</span>
        </div>
        <div className="flex items-center gap-1.5">
          <Button
            variant="ghost"
            size="xs"
            onClick={() => {
              void navigator.clipboard.writeText(activeContent);
            }}
            title="Copy content"
          >
            <Copy className="size-3.5" />
            <span className="hidden sm:inline">Copy</span>
          </Button>
          {!readOnly && (
            <Button
              variant="default"
              size="xs"
              disabled={!isDirty}
              onClick={handleSave}
              className="gap-1"
            >
              <Save className="size-3.5" />
              Save
            </Button>
          )}
        </div>
      </div>

      {/* Editor Area */}
      <div className="relative min-h-0 flex-1 flex overflow-hidden">
        {/* Line Numbers */}
        <div className="select-none bg-surface/50 border-r border-border/60 py-2.5 px-2 text-right text-muted-foreground/50 font-mono text-[11px] leading-[1.6] shrink-0 min-w-[32px] overflow-hidden">
          {Array.from({ length: Math.min(lineCount, 5000) }).map((_, i) => (
            <div key={i}>{i + 1}</div>
          ))}
        </div>

        {/* Textarea */}
        <textarea
          ref={textareaRef}
          value={activeContent}
          onChange={handleChange}
          onKeyDown={handleKeyDown}
          readOnly={readOnly}
          spellCheck={false}
          autoCapitalize="off"
          autoCorrect="off"
          className="h-full w-full resize-none bg-transparent p-2.5 font-mono text-[12.5px] leading-[1.6] text-foreground outline-hidden focus:outline-hidden"
          placeholder="Start typing or editing..."
        />
      </div>
    </div>
  );
}
