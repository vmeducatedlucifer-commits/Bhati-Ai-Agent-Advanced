import { useState } from "react";
import { Mic } from "lucide-react";
import { ChatPanel } from "@/components/chat/ChatPanel";
import { ArtifactsView } from "@/components/computer/ArtifactsView";
import { BrowserView } from "@/components/computer/BrowserView";
import { MobileBottomNav, type MobileTab } from "@/components/mobile/MobileBottomNav";
import { MobileFileExplorer } from "@/components/mobile/MobileFileExplorer";
import { MobileHeader } from "@/components/mobile/MobileHeader";
import { MobileProjectsView } from "@/components/mobile/MobileProjectsView";
import { MobileTerminal } from "@/components/mobile/MobileTerminal";
import { NewProjectDialog } from "@/components/projects/NewProjectDialog";
import { SettingsDialog } from "@/components/settings/SettingsDialog";
import { CallMode } from "@/components/voice/CallMode";
import { useEventStream } from "@/hooks/useEventStream";
import { useVoiceAssistant } from "@/hooks/useVoiceAssistant";
import { hapticMedium } from "@/lib/haptics";
import { useStore } from "@/lib/store";

export function MobileWorkspace() {
  const activeThreadId = useStore((s) => s.activeThreadId);
  const running = useStore((s) => s.running);
  const browserUrl = useStore((s) => s.browserUrl);
  const callActive = useStore((s) => s.callActive);
  const setCallActive = useStore((s) => s.setCallActive);

  const [activeTab, setActiveTab] = useState<MobileTab>("chat");
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [projectOpen, setProjectOpen] = useState(false);

  const voice = useVoiceAssistant();

  // Network adaptation is registered once by the shared Workspace shell.
  useEventStream(activeThreadId);

  return (
    <div className="flex h-full w-full flex-col overflow-hidden bg-background select-none">
      {/* Mobile Top Header with Status Bar Inset */}
      <MobileHeader
        onOpenSettings={() => setSettingsOpen(true)}
        onOpenProjectsList={() => setActiveTab("projects")}
      />

      {/* Main Tab View */}
      <main className="relative min-h-0 flex-1 overflow-hidden">
        {activeTab === "chat" && (
          <div className="h-full pb-16">
            <ChatPanel />
          </div>
        )}

        {activeTab === "terminal" && (
          <div className="h-full">
            <MobileTerminal />
          </div>
        )}

        {activeTab === "files" && (
          <div className="h-full">
            <MobileFileExplorer />
          </div>
        )}

        {activeTab === "artifacts" && (
          <div className="h-full overflow-y-auto pb-18">
            {browserUrl ? (
              <div className="h-full flex flex-col">
                <BrowserView />
              </div>
            ) : (
              <div className="h-full">
                <ArtifactsView />
              </div>
            )}
          </div>
        )}

        {activeTab === "projects" && (
          <div className="h-full">
            <MobileProjectsView
              onNewProject={() => setProjectOpen(true)}
              onSelectProject={() => setActiveTab("chat")}
            />
          </div>
        )}
      </main>

      {/* Android Native Floating Action Button (FAB) for Instant Voice Assistant */}
      {activeTab !== "chat" && (
        <button
          type="button"
          onClick={() => {
            hapticMedium();
            setCallActive(true);
          }}
          className="fixed bottom-20 right-4 z-50 flex size-13 items-center justify-center rounded-full bg-primary text-primary-foreground shadow-xl shadow-primary/30 transition-transform active:scale-90 hover:scale-105"
          title="Instant Voice Mode"
          aria-label="Instant Voice Mode"
        >
          <Mic className="size-6 animate-pulse" />
        </button>
      )}

      {/* Android Material 3 Bottom Navigation Bar */}
      <MobileBottomNav
        activeTab={activeTab}
        onChangeTab={setActiveTab}
        running={running}
      />

      {/* Full-Screen Native Call Mode Overlay & Dialogs */}
      {callActive && <CallMode voice={voice} onClose={() => setCallActive(false)} />}
      <SettingsDialog open={settingsOpen} onOpenChange={setSettingsOpen} />
      <NewProjectDialog open={projectOpen} onOpenChange={setProjectOpen} />
    </div>
  );
}
