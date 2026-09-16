import {
  ChevronDown,
  Cpu,
  FolderOpen,
  Globe,
  Laptop,
  Mic,
  Plus,
  Settings,
  Smartphone,
  Wifi,
  Zap,
} from "lucide-react";
import {
  DropdownMenu,
  DropdownMenuCheckItem,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown";
import { Badge } from "@/components/ui/primitives";
import { displayModelName } from "@/lib/api";
import { hapticLight, hapticMedium } from "@/lib/haptics";
import { activeProject, activeThread, useStore } from "@/lib/store";

interface MobileHeaderProps {
  onOpenSettings: () => void;
  onOpenProjectsList?: () => void;
}

export function MobileHeader({ onOpenSettings, onOpenProjectsList }: MobileHeaderProps) {
  const project = useStore(activeProject);
  const thread = useStore(activeThread);
  const models = useStore((s) => s.models);
  const setModel = useStore((s) => s.setThreadModel);
  const running = useStore((s) => s.running);
  const setCallActive = useStore((s) => s.setCallActive);

  const deviceMode = useStore((s) => s.deviceMode);
  const setDeviceMode = useStore((s) => s.setDeviceMode);
  const networkMode = useStore((s) => s.networkMode);
  const effectiveNetworkMode = useStore((s) => s.effectiveNetworkMode);
  const setNetworkMode = useStore((s) => s.setNetworkMode);
  const networkStats = useStore((s) => s.networkStats);
  const activeProjectId = useStore((s) => s.activeProjectId);
  const createThread = useStore((s) => s.createThread);

  const isUltraLow = effectiveNetworkMode === "ultra_low";

  return (
    <header className="sticky top-0 z-30 flex flex-col w-full border-b border-border/80 bg-surface/95 backdrop-blur-xl pt-[env(safe-area-inset-top,0px)] shadow-xs">
      {/* Top Bar Row */}
      <div className="flex h-13 items-center justify-between px-3">
        {/* Project Selector Chip */}
        <div className="flex min-w-0 items-center gap-1.5">
          <button
            type="button"
            onClick={() => {
              hapticLight();
              onOpenProjectsList?.();
            }}
            className="flex items-center gap-1.5 rounded-full bg-muted/60 px-2.5 py-1 text-xs font-bold text-foreground transition active:scale-95 border border-border/60 hover:bg-muted"
          >
            <FolderOpen className="size-3.5 text-primary shrink-0" />
            <span className="max-w-[120px] truncate">
              {project?.name || "Rawal AI"}
            </span>
            <ChevronDown className="size-3 text-muted-foreground shrink-0" />
          </button>

          {running && (
            <Badge tone="primary" className="h-5 px-1.5 text-[10px] font-medium animate-pulse">
              <span className="size-1.5 rounded-full bg-primary mr-1" />
              Running
            </Badge>
          )}
        </div>

        {/* Right Action Icons */}
        <div className="flex items-center gap-1">
          {/* Network Adaptive Mode Badge */}
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <button
                type="button"
                onClick={hapticLight}
                className={`flex h-7 items-center gap-1 rounded-full px-2 text-[11px] font-mono font-semibold transition active:scale-95 border ${
                  isUltraLow
                    ? "border-emerald-500/40 text-emerald-500 bg-emerald-500/10"
                    : "text-sky-400 border-sky-500/30 bg-sky-500/10"
                }`}
                title="Network Speed Mode"
              >
                {isUltraLow ? <Zap className="size-3" /> : <Wifi className="size-3" />}
                <span>{isUltraLow ? "Low" : "Fast"}</span>
              </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-64 rounded-2xl p-1.5 shadow-xl">
              <DropdownMenuLabel className="flex items-center justify-between px-2.5 py-1.5 text-xs">
                <span>Network Speed</span>
                <span className="font-mono text-[10.5px] text-muted-foreground">
                  {networkStats.effectiveSpeedKbps > 1000
                    ? `${(networkStats.effectiveSpeedKbps / 1024).toFixed(1)} Mb/s`
                    : `${networkStats.effectiveSpeedKbps} kbps`}
                </span>
              </DropdownMenuLabel>
              <DropdownMenuItem onSelect={() => { hapticLight(); setNetworkMode("auto"); }} className="rounded-xl">
                <Globe className="size-4 text-primary" />
                <span className="flex-1">
                  <span className="block font-medium text-xs">Auto Detect</span>
                  <span className="block text-[10.5px] text-muted-foreground">Adapts to speed</span>
                </span>
                {networkMode === "auto" && <span className="text-xs text-primary font-bold">✓</span>}
              </DropdownMenuItem>
              <DropdownMenuItem onSelect={() => { hapticLight(); setNetworkMode("ultra_low"); }} className="rounded-xl">
                <Zap className="size-4 text-emerald-500" />
                <span className="flex-1">
                  <span className="block font-medium text-xs">Ultra-Low (&lt;40 kbps)</span>
                  <span className="block text-[10.5px] text-muted-foreground">Zero lag, fast stream</span>
                </span>
                {networkMode === "ultra_low" && <span className="text-xs text-emerald-500 font-bold">✓</span>}
              </DropdownMenuItem>
              <DropdownMenuItem onSelect={() => { hapticLight(); setNetworkMode("high_speed"); }} className="rounded-xl">
                <Wifi className="size-4 text-sky-400" />
                <span className="flex-1">
                  <span className="block font-medium text-xs">High Speed (Pro UI)</span>
                  <span className="block text-[10.5px] text-muted-foreground">Monaco & full graphics</span>
                </span>
                {networkMode === "high_speed" && <span className="text-xs text-sky-400 font-bold">✓</span>}
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuLabel className="px-2.5 py-1 text-xs">Device Mode</DropdownMenuLabel>
              <DropdownMenuItem onSelect={() => { hapticLight(); setDeviceMode("mobile"); }} className="rounded-xl">
                <Smartphone className="size-4" />
                <span className="flex-1 text-xs">Android Mobile</span>
                {deviceMode === "mobile" && <span className="text-xs text-primary font-bold">✓</span>}
              </DropdownMenuItem>
              <DropdownMenuItem onSelect={() => { hapticLight(); setDeviceMode("desktop"); }} className="rounded-xl">
                <Laptop className="size-4" />
                <span className="flex-1 text-xs">Desktop PC</span>
                {deviceMode === "desktop" && <span className="text-xs text-primary font-bold">✓</span>}
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>

          {/* Model Chip */}
          {thread && (
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <button
                  type="button"
                  onClick={hapticLight}
                  className="flex h-7 items-center gap-1 rounded-full bg-muted/60 px-2 text-[11px] font-medium text-foreground border border-border/60 transition active:scale-95"
                >
                  <Cpu className="size-3 text-primary" />
                  <span className="max-w-[75px] truncate">{displayModelName(thread.model || "Model")}</span>
                </button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="max-h-80 w-64 overflow-y-auto rounded-2xl p-1.5 shadow-xl">
                <DropdownMenuLabel className="px-2.5 py-1 text-xs">AI Model</DropdownMenuLabel>
                {models.map((option) => (
                  <DropdownMenuCheckItem
                    key={`${option.provider_id}:${option.model}`}
                    checked={thread.model === option.model && thread.provider_id === option.provider_id}
                    onSelect={() => {
                      hapticLight();
                      void setModel(option.provider_id, option.model);
                    }}
                    className="rounded-xl"
                  >
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-xs font-medium">{displayModelName(option.model)}</span>
                      <span className="block text-[10px] text-muted-foreground">{option.provider}</span>
                    </span>
                  </DropdownMenuCheckItem>
                ))}
              </DropdownMenuContent>
            </DropdownMenu>
          )}

          {/* Voice Mic Trigger */}
          <button
            type="button"
            onClick={() => {
              hapticMedium();
              setCallActive(true);
            }}
            className="flex size-7 items-center justify-center rounded-full bg-primary/10 text-primary transition active:scale-90 hover:bg-primary/20"
            title="Live Voice Mode"
          >
            <Mic className="size-4" />
          </button>

          {/* New Chat Button */}
          {activeProjectId && (
            <button
              type="button"
              onClick={() => {
                hapticLight();
                void createThread(activeProjectId);
              }}
              className="flex size-7 items-center justify-center rounded-full text-muted-foreground transition active:scale-90 hover:bg-muted hover:text-foreground"
              title="New Chat"
            >
              <Plus className="size-4" />
            </button>
          )}

          {/* Settings Button */}
          <button
            type="button"
            onClick={() => {
              hapticLight();
              onOpenSettings();
            }}
            className="flex size-7 items-center justify-center rounded-full text-muted-foreground transition active:scale-90 hover:bg-muted hover:text-foreground"
            title="Settings"
          >
            <Settings className="size-4" />
          </button>
        </div>
      </div>
    </header>
  );
}
