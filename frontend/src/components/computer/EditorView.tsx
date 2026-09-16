import Editor from "@monaco-editor/react";
import { FileCode2, GitCompare, Save, Zap } from "lucide-react";
import { useEffect, useState } from "react";
import { DiffView } from "@/components/chat/DiffView";
import { LightweightEditor } from "@/components/computer/LightweightEditor";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/primitives";
import { useStore } from "@/lib/store";
import { fileLanguage } from "@/lib/utils";

const MONACO_OPTIONS = {
  fontFamily: "JetBrains Mono, ui-monospace, monospace",
  fontSize: 12.5,
  lineHeight: 1.6,
  minimap: { enabled: false },
  scrollBeyondLastLine: false,
  smoothScrolling: true,
  renderLineHighlight: "gutter" as const,
  padding: { top: 12, bottom: 12 },
  tabSize: 2,
  automaticLayout: true,
  scrollbar: { verticalScrollbarSize: 9, horizontalScrollbarSize: 9 },
};

export function EditorView() {
  const openFile = useStore((s) => s.openFile);
  const activeDiff = useStore((s) => s.activeDiff);
  const setContent = useStore((s) => s.setOpenFileContent);
  const save = useStore((s) => s.saveOpenFile);
  const effectiveNetworkMode = useStore((s) => s.effectiveNetworkMode);
  const [showDiff, setShowDiff] = useState(true);
  const [forceMonaco, setForceMonaco] = useState(false);

  const useLightweight = effectiveNetworkMode === "ultra_low" && !forceMonaco;

  useEffect(() => {
    if (activeDiff) setShowDiff(true);
  }, [activeDiff]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key === "s") {
        event.preventDefault();
        void save();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [save]);

  if (activeDiff && showDiff) {
    return (
      <div className="flex h-full flex-col">
        <div className="flex items-center gap-2 border-b border-border px-3 py-1.5">
          <GitCompare className="size-3.5 text-primary" />
          <span className="truncate font-mono text-[12px]">{activeDiff.path}</span>
          <Button
            variant="ghost"
            size="xs"
            className="ml-auto"
            onClick={() => setShowDiff(false)}
          >
            Edit file
          </Button>
        </div>
        <div className="scrollbar-thin min-h-0 flex-1 overflow-auto p-3">
          <DiffView diff={activeDiff.diff} />
        </div>
      </div>
    );
  }

  if (!openFile) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-2 text-center text-muted-foreground">
        <FileCode2 className="size-8 opacity-40" />
        <p className="text-[13px]">Open a file from the tree, or let the agent edit one.</p>
      </div>
    );
  }

  if (useLightweight) {
    return (
      <div className="flex h-full flex-col">
        <div className="flex items-center justify-between border-b border-border bg-muted/40 px-3 py-1 text-[11px] text-muted-foreground">
          <span className="inline-flex items-center gap-1 text-emerald-500 font-medium">
            <Zap className="size-3" /> Ultra-Light Fast Editor (&lt;40kbps optimized)
          </span>
          <Button
            variant="ghost"
            size="xs"
            className="h-5 text-[10.5px] px-1.5 text-muted-foreground"
            onClick={() => setForceMonaco(true)}
          >
            Load Full Monaco
          </Button>
        </div>
        <div className="min-h-0 flex-1">
          <LightweightEditor />
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center gap-2 border-b border-border px-3 py-1.5">
        <span className="truncate font-mono text-[12px]">{openFile.path}</span>
        {openFile.dirty ? <Badge tone="warning">unsaved</Badge> : null}
        <Button
          variant="ghost"
          size="xs"
          className="ml-auto"
          disabled={!openFile.dirty}
          onClick={() => void save()}
        >
          <Save className="size-3.5" />
          Save
        </Button>
      </div>
      <div className="min-h-0 flex-1">
        <Editor
          theme="vs-dark"
          language={fileLanguage(openFile.path)}
          value={openFile.content}
          onChange={(value) => setContent(value ?? "")}
          options={MONACO_OPTIONS}
          loading={<div className="p-4 text-[13px] text-muted-foreground">Loading editor…</div>}
        />
      </div>
    </div>
  );
}
