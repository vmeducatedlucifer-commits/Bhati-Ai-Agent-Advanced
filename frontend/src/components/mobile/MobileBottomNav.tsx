import {
  Code2,
  FolderTree,
  Layers,
  MessageSquare,
  Terminal,
} from "lucide-react";
import { hapticLight } from "@/lib/haptics";
import { cn } from "@/lib/utils";

export type MobileTab = "chat" | "terminal" | "files" | "artifacts" | "projects";

interface MobileBottomNavProps {
  activeTab: MobileTab;
  onChangeTab: (tab: MobileTab) => void;
  running?: boolean;
}

export function MobileBottomNav({
  activeTab,
  onChangeTab,
  running = false,
}: MobileBottomNavProps) {
  const tabs = [
    { id: "chat" as MobileTab, label: "Chat", icon: MessageSquare, badge: running },
    { id: "terminal" as MobileTab, label: "Terminal", icon: Terminal },
    { id: "files" as MobileTab, label: "Files", icon: Code2 },
    { id: "artifacts" as MobileTab, label: "Preview", icon: Layers },
    { id: "projects" as MobileTab, label: "Projects", icon: FolderTree },
  ];

  const handleSelect = (tab: MobileTab) => {
    hapticLight();
    onChangeTab(tab);
  };

  return (
    <nav className="fixed inset-x-0 bottom-0 z-40 flex h-16 items-center justify-around border-t border-border/80 bg-surface/95 px-3 backdrop-blur-xl pb-[env(safe-area-inset-bottom,0px)] shadow-lg shadow-black/20">
      {tabs.map((tab) => {
        const Icon = tab.icon;
        const isActive = activeTab === tab.id;
        return (
          <button
            key={tab.id}
            type="button"
            onClick={() => handleSelect(tab.id)}
            className="group relative flex flex-1 flex-col items-center justify-center py-1 transition-all active:scale-95"
            aria-label={tab.label}
          >
            {/* Material 3 Active Pill Indicator */}
            <div
              className={cn(
                "relative flex h-8 w-14 items-center justify-center rounded-full transition-all duration-300",
                isActive
                  ? "bg-primary/20 text-primary shadow-xs"
                  : "text-muted-foreground group-hover:bg-muted/40 group-hover:text-foreground",
              )}
            >
              <Icon
                className={cn(
                  "size-5 transition-transform duration-200",
                  isActive ? "scale-105 stroke-[2.4]" : "stroke-[1.8]",
                )}
              />
              {tab.badge && (
                <span className="absolute right-3.5 top-1.5 size-2 animate-pulse rounded-full bg-primary ring-2 ring-background" />
              )}
            </div>

            {/* Label */}
            <span
              className={cn(
                "mt-0.5 text-[11px] font-medium tracking-tight transition-colors duration-200",
                isActive ? "font-bold text-primary" : "text-muted-foreground",
              )}
            >
              {tab.label}
            </span>
          </button>
        );
      })}
    </nav>
  );
}
