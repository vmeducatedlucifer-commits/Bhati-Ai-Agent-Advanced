import { useCallback, useEffect, useRef, useState } from "react";
import { cn } from "@/lib/utils";

/** Draggable two-pane split with a persisted ratio, adapting to mobile. */
export function SplitPane({
  left,
  right,
  showRight,
  storageKey = "rawal.split",
  min = 22,
  max = 78,
  initial = 55,
}: {
  left: React.ReactNode;
  right: React.ReactNode;
  showRight: boolean;
  storageKey?: string;
  min?: number;
  max?: number;
  initial?: number;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [ratio, setRatio] = useState(() => Number(localStorage.getItem(storageKey)) || initial);
  const [dragging, setDragging] = useState(false);

  const onMove = useCallback(
    (clientX: number) => {
      const rect = containerRef.current?.getBoundingClientRect();
      if (!rect) return;
      const next = Math.min(max, Math.max(min, ((clientX - rect.left) / rect.width) * 100));
      setRatio(next);
    },
    [min, max],
  );

  useEffect(() => {
    if (!dragging) return;
    const move = (e: MouseEvent) => onMove(e.clientX);
    const up = () => {
      setDragging(false);
      localStorage.setItem(storageKey, String(ratio));
    };
    window.addEventListener("mousemove", move);
    window.addEventListener("mouseup", up);
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
    return () => {
      window.removeEventListener("mousemove", move);
      window.removeEventListener("mouseup", up);
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
    };
  }, [dragging, onMove, ratio, storageKey]);

  return (
    <div ref={containerRef} className="flex min-h-0 flex-1 relative">
      {/* LEFT PANE (Chat): Hidden on mobile if showRight is true, visible on desktop */}
      <div
        className={cn(
          "min-w-0 flex-1 h-full",
          showRight ? "hidden md:block" : "block"
        )}
        style={{ flex: showRight ? `0 0 ${ratio}%` : undefined }}
      >
        {left}
      </div>

      {showRight && (
        <>
          {/* DRAG HANDLE: Only visible on desktop */}
          <div
            role="separator"
            aria-orientation="vertical"
            onMouseDown={() => setDragging(true)}
            onDoubleClick={() => setRatio(initial)}
            className={cn(
              "hidden md:block group relative w-px shrink-0 cursor-col-resize bg-border transition-colors",
              dragging && "bg-primary",
            )}
          >
            <span className="absolute inset-y-0 -left-1.5 -right-1.5 group-hover:bg-primary/20" />
          </div>

          {/* RIGHT PANE (Workspace): Full screen on mobile, flexible on desktop */}
          <div className="flex-1 min-w-0 h-full w-full absolute inset-0 md:relative z-20 md:z-0 bg-background">
            {right}
          </div>
        </>
      )}
    </div>
  );
}
