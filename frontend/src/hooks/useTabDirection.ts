import { useEffect, useRef, useState } from "react";

export type TabDir = "left" | "right";

/**
 * Directional tab motion, shared project-wide.
 *
 * Given the ordered tab values and the active one, returns the navigation
 * direction (forward in the order → content slides in from the right,
 * backward → from the left) plus a ref for the scrollable tab strip. The
 * active trigger is always scrolled into view, so it can never end up hidden
 * off-screen. Consumed via a `data-tab-dir` attribute + `.anim-tab-slide`.
 */
export function useTabDirection(order: string[], active: string): {
  dir: TabDir;
  listRef: React.RefObject<HTMLDivElement>;
  scrollStrip: (delta: number) => void;
} {
  const [dir, setDir] = useState<TabDir>("right");
  const prevRef = useRef(active);
  const listRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const prev = prevRef.current;
    if (prev !== active) {
      const from = order.indexOf(prev);
      const to = order.indexOf(active);
      setDir(to < from && from !== -1 ? "left" : "right");
      prevRef.current = active;
    }
    // Keep the selected tab visible — the strip may overflow on small screens.
    requestAnimationFrame(() => {
      listRef.current
        ?.querySelector('[data-state="active"]')
        ?.scrollIntoView({ behavior: "smooth", inline: "center", block: "nearest" });
    });
  }, [active, order]);

  const scrollStrip = (delta: number) => {
    listRef.current?.scrollBy({ left: delta, behavior: "smooth" });
  };

  return { dir, listRef, scrollStrip };
}
