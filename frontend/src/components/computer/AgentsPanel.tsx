/**
 * AgentsPanel — Full-featured subagent & swarm management dashboard.
 */

import { useState, useEffect, useCallback } from "react";
import { useStore } from "@/lib/store";
import { api } from "@/lib/api";
import type { SubAgentInfo, SubAgentListItem, SwarmInfo, AgentType, AgentPriority, SwarmStrategy } from "@/types";

const AGENT_TYPE_CONFIG: Record<string, { icon: string; color: string; label: string }> = {
  explorer: { icon: "🔍", color: "bg-blue-500", label: "Explorer" },
  coder: { icon: "💻", color: "bg-green-500", label: "Coder" },
  reviewer: { icon: "🔎", color: "bg-purple-500", label: "Reviewer" },
  researcher: { icon: "📚", color: "bg-orange-500", label: "Researcher" },
  planner: { icon: "📋", color: "bg-yellow-500", label: "Planner" },
  tester: { icon: "🧪", color: "bg-red-500", label: "Tester" },
  deployer: { icon: "🚀", color: "bg-pink-500", label: "Deployer" },
  monitor: { icon: "📊", color: "bg-teal-500", label: "Monitor" },
  coordinator: { icon: "🎯", color: "bg-indigo-500", label: "Coordinator" },
};

const PRIORITY_CONFIG: Record<string, { icon: string; color: string; label: string }> = {
  critical: { icon: "🔴", color: "text-red-500", label: "Critical" },
  high: { icon: "🟠", color: "text-orange-500", label: "High" },
  normal: { icon: "🔵", color: "text-blue-500", label: "Normal" },
  low: { icon: "⚪", color: "text-gray-400", label: "Low" },
  background: { icon: "⬛", color: "text-gray-600", label: "Background" },
};

const STATUS_CONFIG: Record<string, { icon: string; color: string; label: string; pulse: boolean }> = {
  queued: { icon: "⏳", color: "bg-gray-500/20 text-gray-400", label: "Queued", pulse: false },
  spawning: { icon: "🔄", color: "bg-blue-500/20 text-blue-400", label: "Spawning", pulse: true },
  running: { icon: "▶️", color: "bg-green-500/20 text-green-400", label: "Running", pulse: true },
  paused: { icon: "⏸️", color: "bg-yellow-500/20 text-yellow-400", label: "Paused", pulse: false },
  completed: { icon: "✅", color: "bg-emerald-500/20 text-emerald-400", label: "Completed", pulse: false },
  failed: { icon: "❌", color: "bg-red-500/20 text-red-400", label: "Failed", pulse: false },
  killed: { icon: "☠️", color: "bg-gray-500/20 text-gray-500", label: "Killed", pulse: false },
};

const STRATEGY_CONFIG: Record<string, { icon: string; label: string; desc: string }> = {
  parallel: { icon: "⚡", label: "Parallel", desc: "All agents run simultaneously" },
  sequential: { icon: "🔗", label: "Sequential", desc: "Agents run one after another" },
  map_reduce: { icon: "🗺️", label: "Map-Reduce", desc: "Split → parallel → merge" },
  hierarchical: { icon: "🏗️", label: "Hierarchical", desc: "Coordinator delegates to workers" },
};

function StatusBadge({ status }: { status: string }) {
  const cfg = STATUS_CONFIG[status] || STATUS_CONFIG.queued;
  return (
    <span className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded-full text-[10px] font-medium ${cfg.color} ${cfg.pulse ? "animate-pulse" : ""}`}>
      {cfg.icon} {cfg.label}
    </span>
  );
}

function PriorityBadge({ priority }: { priority: string }) {
  const cfg = PRIORITY_CONFIG[priority] || PRIORITY_CONFIG.normal;
  return <span className={`inline-flex items-center gap-0.5 text-[10px] ${cfg.color}`}>{cfg.icon} {cfg.label}</span>;
}

function TypeBadge({ type }: { type: string }) {
  const cfg = AGENT_TYPE_CONFIG[type] || { icon: "🤖", color: "bg-gray-500", label: type };
  return <span className={`inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[10px] font-medium text-white ${cfg.color}`}>{cfg.icon} {cfg.label}</span>;
}

function DurationDisplay({ ms }: { ms: number }) {
  if (!ms) return <span className="text-[10px] text-muted-foreground">—</span>;
  if (ms < 1000) return <span className="text-[10px] text-muted-foreground">{ms}ms</span>;
  if (ms < 60000) return <span className="text-[10px] text-muted-foreground">{(ms / 1000).toFixed(1)}s</span>;
  return <span className="text-[10px] text-muted-foreground">{(ms / 60000).toFixed(1)}m</span>;
}

function AgentDetail({ agent, onClose, onKill }: { agent: SubAgentInfo; onClose: () => void; onKill: (id: string) => void }) {
  const typeCfg = AGENT_TYPE_CONFIG[agent.agent_type] || { icon: "🤖", label: agent.agent_type };
  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center justify-between p-2 border-b border-border">
        <div className="flex items-center gap-2">
          <span className="text-base">{typeCfg.icon}</span>
          <div>
            <h3 className="font-semibold text-xs">{agent.name}</h3>
            <div className="flex items-center gap-1 mt-0.5">
              <TypeBadge type={agent.agent_type} />
              <PriorityBadge priority={agent.priority} />
              <StatusBadge status={agent.status} />
            </div>
          </div>
        </div>
        <div className="flex items-center gap-1">
          {agent.is_live && <button onClick={() => onKill(agent.id)} className="px-1.5 py-0.5 text-[10px] bg-red-500/20 text-red-400 hover:bg-red-500/30 rounded">☠️ Kill</button>}
          <button onClick={onClose} className="px-1.5 py-0.5 text-[10px] bg-secondary hover:bg-secondary/80 rounded">✕</button>
        </div>
      </div>
      <div className="flex-1 overflow-y-auto p-2 space-y-2 text-xs">
        <div className="grid grid-cols-2 gap-1.5">
          <div className="p-1.5 rounded bg-muted/50"><div className="text-[10px] text-muted-foreground">ID</div><div className="font-mono text-[10px] truncate">{agent.id}</div></div>
          <div className="p-1.5 rounded bg-muted/50"><div className="text-[10px] text-muted-foreground">Duration</div><DurationDisplay ms={agent.duration_ms} /></div>
          <div className="p-1.5 rounded bg-muted/50"><div className="text-[10px] text-muted-foreground">Steps</div><div className="text-[10px]">{agent.steps_completed}/{agent.max_steps}</div></div>
          <div className="p-1.5 rounded bg-muted/50"><div className="text-[10px] text-muted-foreground">Live</div><div className="text-[10px]">{agent.is_live ? "🟢 Yes" : "⚫ No"}</div></div>
        </div>
        {agent.prompt && <div><div className="text-[10px] font-medium text-muted-foreground mb-0.5">Prompt</div><div className="p-1.5 rounded bg-muted/50 text-[10px] whitespace-pre-wrap max-h-24 overflow-y-auto">{agent.prompt}</div></div>}
        {agent.result && <div><div className="text-[10px] font-medium text-muted-foreground mb-0.5">Result</div><div className="p-1.5 rounded bg-emerald-500/10 border border-emerald-500/20 text-[10px] whitespace-pre-wrap max-h-40 overflow-y-auto">{agent.result}</div></div>}
        {agent.error && <div><div className="text-[10px] font-medium text-muted-foreground mb-0.5">Error</div><div className="p-1.5 rounded bg-red-500/10 border border-red-500/20 text-[10px] whitespace-pre-wrap max-h-24 overflow-y-auto">{agent.error}</div></div>}
      </div>
    </div>
  );
}

function SwarmDetail({ swarm, onClose, onKill }: { swarm: SwarmInfo; onClose: () => void; onKill: (id: string) => void }) {
  const stratCfg = STRATEGY_CONFIG[swarm.strategy] || { icon: "🐝", label: swarm.strategy };
  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center justify-between p-2 border-b border-border">
        <div className="flex items-center gap-2">
          <span className="text-base">{stratCfg.icon}</span>
          <div>
            <h3 className="font-semibold text-xs">🐝 {swarm.name}</h3>
            <div className="flex items-center gap-1 mt-0.5"><StatusBadge status={swarm.status} /></div>
          </div>
        </div>
        <div className="flex items-center gap-1">
          {swarm.status === "running" && <button onClick={() => onKill(swarm.id)} className="px-1.5 py-0.5 text-[10px] bg-red-500/20 text-red-400 hover:bg-red-500/30 rounded">☠️ Kill</button>}
          <button onClick={onClose} className="px-1.5 py-0.5 text-[10px] bg-secondary hover:bg-secondary/80 rounded">✕</button>
        </div>
      </div>
      <div className="p-2 border-b border-border">
        <div className="flex items-center justify-between text-[10px] mb-1"><span className="text-muted-foreground">Progress</span><span>{swarm.completed_count}/{swarm.agent_count}</span></div>
        <div className="w-full bg-muted rounded-full h-1.5"><div className="bg-emerald-500 h-1.5 rounded-full transition-all" style={{ width: `${swarm.agent_count ? (swarm.completed_count / swarm.agent_count) * 100 : 0}%` }} /></div>
      </div>
      <div className="flex-1 overflow-y-auto p-2 space-y-1">
        <div className="text-[10px] font-medium text-muted-foreground mb-1">Agents</div>
        {(swarm.agents || []).map((agent) => {
          const typeCfg = AGENT_TYPE_CONFIG[agent.agent_type] || { icon: "🤖", label: agent.agent_type };
          return (
            <div key={agent.id} className="flex items-center justify-between p-1.5 rounded bg-muted/30 hover:bg-muted/50">
              <div className="flex items-center gap-1.5">
                <span className="text-xs">{typeCfg.icon}</span>
                <div><div className="text-[10px] font-medium">{agent.name}</div><div className="flex items-center gap-1"><StatusBadge status={agent.status} /><PriorityBadge priority={agent.priority} /></div></div>
              </div>
              <div className="flex items-center gap-1.5"><DurationDisplay ms={agent.duration_ms} />{agent.is_live && <span className="w-1.5 h-1.5 rounded-full bg-green-500 animate-pulse" />}</div>
            </div>
          );
        })}
      </div>
      {swarm.result && <div className="p-2 border-t border-border"><div className="text-[10px] font-medium text-muted-foreground mb-0.5">Result</div><div className="p-1.5 rounded bg-emerald-500/10 border border-emerald-500/20 text-[10px] whitespace-pre-wrap max-h-24 overflow-y-auto">{swarm.result}</div></div>}
    </div>
  );
}

function SpawnDialog({ onClose, onSpawn }: { onClose: () => void; onSpawn: (data: { agent_type: string; name: string; prompt: string; priority?: string; max_steps?: number }) => void }) {
  const [agentType, setAgentType] = useState<AgentType>("coder");
  const [name, setName] = useState("");
  const [prompt, setPrompt] = useState("");
  const [priority, setPriority] = useState<AgentPriority>("normal");
  const [maxSteps, setMaxSteps] = useState(25);

  const handleSubmit = () => {
    if (!prompt.trim()) return;
    onSpawn({ agent_type: agentType, name: name || `${agentType}-${Date.now().toString(36)}`, prompt: prompt.trim(), priority, max_steps: maxSteps });
    onClose();
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50" onClick={onClose}>
      <div className="bg-background border border-border rounded-lg shadow-xl w-full max-w-md p-4 space-y-3" onClick={(e) => e.stopPropagation()}>
        <h3 className="font-semibold text-sm">🤖 Spawn SubAgent</h3>
        <div>
          <label className="text-xs text-muted-foreground">Agent Type</label>
          <div className="grid grid-cols-3 gap-1 mt-1">
            {Object.entries(AGENT_TYPE_CONFIG).map(([type, cfg]) => (
              <button key={type} onClick={() => setAgentType(type as AgentType)} className={`px-1.5 py-1 text-[10px] rounded transition-colors ${agentType === type ? `${cfg.color} text-white` : "bg-muted hover:bg-muted/80"}`}>{cfg.icon} {cfg.label}</button>
            ))}
          </div>
        </div>
        <div><label className="text-xs text-muted-foreground">Name</label><input type="text" value={name} onChange={(e) => setName(e.target.value)} placeholder="Auto-generated" className="w-full mt-1 px-2 py-1 text-xs bg-muted rounded border border-border focus:outline-none focus:ring-1 focus:ring-primary" /></div>
        <div><label className="text-xs text-muted-foreground">Prompt</label><textarea value={prompt} onChange={(e) => setPrompt(e.target.value)} placeholder="Full instructions for the agent..." rows={3} className="w-full mt-1 px-2 py-1 text-xs bg-muted rounded border border-border focus:outline-none focus:ring-1 focus:ring-primary resize-none" /></div>
        <div className="grid grid-cols-2 gap-2">
          <div><label className="text-xs text-muted-foreground">Priority</label><select value={priority} onChange={(e) => setPriority(e.target.value as AgentPriority)} className="w-full mt-1 px-2 py-1 text-xs bg-muted rounded border border-border">{Object.entries(PRIORITY_CONFIG).map(([key, cfg]) => <option key={key} value={key}>{cfg.icon} {cfg.label}</option>)}</select></div>
          <div><label className="text-xs text-muted-foreground">Max Steps</label><input type="number" value={maxSteps} onChange={(e) => setMaxSteps(Number(e.target.value))} min={5} max={100} className="w-full mt-1 px-2 py-1 text-xs bg-muted rounded border border-border" /></div>
        </div>
        <div className="flex justify-end gap-2 pt-1">
          <button onClick={onClose} className="px-3 py-1 text-xs bg-secondary hover:bg-secondary/80 rounded">Cancel</button>
          <button onClick={handleSubmit} disabled={!prompt.trim()} className="px-3 py-1 text-xs bg-primary text-primary-foreground hover:bg-primary/90 rounded disabled:opacity-50">🚀 Spawn</button>
        </div>
      </div>
    </div>
  );
}

function SwarmDeployDialog({ onClose, onDeploy }: { onClose: () => void; onDeploy: (data: { name: string; prompt: string; strategy?: string; agent_count?: number; agent_type?: string; priority?: string; max_steps?: number }) => void }) {
  const [name, setName] = useState("");
  const [prompt, setPrompt] = useState("");
  const [strategy, setStrategy] = useState<SwarmStrategy>("parallel");
  const [agentCount, setAgentCount] = useState(3);
  const [agentType, setAgentType] = useState<AgentType>("coder");
  const [priority, setPriority] = useState<AgentPriority>("normal");

  const handleSubmit = () => {
    if (!prompt.trim()) return;
    onDeploy({ name: name || `swarm-${Date.now().toString(36)}`, prompt: prompt.trim(), strategy, agent_count: agentCount, agent_type: agentType, priority });
    onClose();
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50" onClick={onClose}>
      <div className="bg-background border border-border rounded-lg shadow-xl w-full max-w-md p-4 space-y-3" onClick={(e) => e.stopPropagation()}>
        <h3 className="font-semibold text-sm">🐝 Deploy Swarm</h3>
        <div>
          <label className="text-xs text-muted-foreground">Strategy</label>
          <div className="grid grid-cols-2 gap-1 mt-1">
            {Object.entries(STRATEGY_CONFIG).map(([key, cfg]) => (
              <button key={key} onClick={() => setStrategy(key as SwarmStrategy)} className={`px-2 py-1.5 text-[10px] rounded transition-colors text-left ${strategy === key ? "bg-primary text-primary-foreground" : "bg-muted hover:bg-muted/80"}`}>
                <div className="font-medium">{cfg.icon} {cfg.label}</div>
                <div className="text-[9px] opacity-70 mt-0.5">{cfg.desc}</div>
              </button>
            ))}
          </div>
        </div>
        <div><label className="text-xs text-muted-foreground">Name</label><input type="text" value={name} onChange={(e) => setName(e.target.value)} placeholder="Auto-generated" className="w-full mt-1 px-2 py-1 text-xs bg-muted rounded border border-border focus:outline-none focus:ring-1 focus:ring-primary" /></div>
        <div><label className="text-xs text-muted-foreground">Task</label><textarea value={prompt} onChange={(e) => setPrompt(e.target.value)} placeholder="Describe the task..." rows={2} className="w-full mt-1 px-2 py-1 text-xs bg-muted rounded border border-border focus:outline-none focus:ring-1 focus:ring-primary resize-none" /></div>
        <div className="grid grid-cols-3 gap-2">
          <div><label className="text-xs text-muted-foreground">Agents</label><input type="number" value={agentCount} onChange={(e) => setAgentCount(Number(e.target.value))} min={1} max={20} className="w-full mt-1 px-2 py-1 text-xs bg-muted rounded border border-border" /></div>
          <div><label className="text-xs text-muted-foreground">Type</label><select value={agentType} onChange={(e) => setAgentType(e.target.value as AgentType)} className="w-full mt-1 px-2 py-1 text-xs bg-muted rounded border border-border">{Object.entries(AGENT_TYPE_CONFIG).map(([key, cfg]) => <option key={key} value={key}>{cfg.icon} {cfg.label}</option>)}</select></div>
          <div><label className="text-xs text-muted-foreground">Priority</label><select value={priority} onChange={(e) => setPriority(e.target.value as AgentPriority)} className="w-full mt-1 px-2 py-1 text-xs bg-muted rounded border border-border">{Object.entries(PRIORITY_CONFIG).map(([key, cfg]) => <option key={key} value={key}>{cfg.icon} {cfg.label}</option>)}</select></div>
        </div>
        <div className="flex justify-end gap-2 pt-1">
          <button onClick={onClose} className="px-3 py-1 text-xs bg-secondary hover:bg-secondary/80 rounded">Cancel</button>
          <button onClick={handleSubmit} disabled={!prompt.trim()} className="px-3 py-1 text-xs bg-primary text-primary-foreground hover:bg-primary/90 rounded disabled:opacity-50">🐝 Deploy</button>
        </div>
      </div>
    </div>
  );
}

export default function AgentsPanel() {
  const subAgents = useStore((s) => s.subAgents) ?? [];
  const swarms = useStore((s) => s.swarms) ?? [];
  const selectedAgentId = useStore((s) => s.selectedAgentId);
  const selectedSwarmId = useStore((s) => s.selectedSwarmId);
  const activeThreadId = useStore((s) => s.activeThreadId);
  const refreshSubAgents = useStore((s) => s.refreshSubAgents);
  const refreshSwarms = useStore((s) => s.refreshSwarms);
  const selectAgent = useStore((s) => s.selectAgent);
  const selectSwarm = useStore((s) => s.selectSwarm);
  const spawnAgent = useStore((s) => s.spawnAgent);
  const killAgent = useStore((s) => s.killAgent);
  const killAllAgents = useStore((s) => s.killAllAgents);
  const deploySwarmAction = useStore((s) => s.deploySwarmAction);
  const killSwarmAction = useStore((s) => s.killSwarmAction);

  const [showSpawn, setShowSpawn] = useState(false);
  const [showSwarmDeploy, setShowSwarmDeploy] = useState(false);
  const [detailAgent, setDetailAgent] = useState<SubAgentInfo | null>(null);
  const [detailSwarm, setDetailSwarm] = useState<SwarmInfo | null>(null);
  const [tab, setTab] = useState<"agents" | "swarms">("agents");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!activeThreadId) return;
    setError(null);
    const doRefresh = async () => {
      try { await refreshSubAgents(); } catch (e) { setError(String(e)); }
      try { await refreshSwarms(); } catch (e) { setError(String(e)); }
    };
    void doRefresh();
    const interval = setInterval(() => { void doRefresh(); }, 3000);
    return () => clearInterval(interval);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeThreadId]);

  useEffect(() => {
    if (selectedAgentId && activeThreadId) {
      api.getSubAgentStatus(activeThreadId, selectedAgentId).then(setDetailAgent).catch(() => setDetailAgent(null));
    } else { setDetailAgent(null); }
  }, [selectedAgentId, activeThreadId]);

  useEffect(() => {
    if (selectedSwarmId && activeThreadId) {
      api.getSwarmStatus(activeThreadId, selectedSwarmId).then(setDetailSwarm).catch(() => setDetailSwarm(null));
    } else { setDetailSwarm(null); }
  }, [selectedSwarmId, activeThreadId]);

  const handleKillAgent = useCallback(async (agentId: string) => {
    await killAgent(agentId);
    selectAgent(null);
    setDetailAgent(null);
  }, [killAgent, selectAgent]);

  const handleKillSwarm = useCallback(async (swarmId: string) => {
    await killSwarmAction(swarmId);
    selectSwarm(null);
    setDetailSwarm(null);
  }, [killSwarmAction, selectSwarm]);

  const runningCount = subAgents.filter((a) => a.is_live || a.status === "running" || a.status === "spawning").length;

  // No thread selected
  if (!activeThreadId) {
    return (
      <div className="flex flex-col items-center justify-center h-full text-muted-foreground p-4">
        <span className="text-2xl mb-1">🤖</span>
        <p className="text-xs">No active thread</p>
        <p className="text-[10px] mt-0.5">Start a conversation to manage agents</p>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full">
      {/* Toolbar */}
      <div className="flex items-center justify-between p-2 border-b border-border">
        <div className="flex items-center gap-1.5">
          <button onClick={() => setTab("agents")} className={`px-2 py-1 text-[10px] rounded transition-colors ${tab === "agents" ? "bg-primary text-primary-foreground" : "bg-muted hover:bg-muted/80"}`}>🤖 Agents ({subAgents.length})</button>
          <button onClick={() => setTab("swarms")} className={`px-2 py-1 text-[10px] rounded transition-colors ${tab === "swarms" ? "bg-primary text-primary-foreground" : "bg-muted hover:bg-muted/80"}`}>🐝 Swarms ({swarms.length})</button>
        </div>
        <div className="flex items-center gap-1">
          {runningCount > 0 && <span className="flex items-center gap-1 px-1.5 py-0.5 text-[10px] bg-green-500/20 text-green-400 rounded"><span className="w-1.5 h-1.5 rounded-full bg-green-500 animate-pulse" />{runningCount}</span>}
          <button onClick={() => setShowSpawn(true)} className="px-1.5 py-0.5 text-[10px] bg-primary text-primary-foreground hover:bg-primary/90 rounded">+ Spawn</button>
          <button onClick={() => setShowSwarmDeploy(true)} className="px-1.5 py-0.5 text-[10px] bg-indigo-500 text-white hover:bg-indigo-500/90 rounded">🐝 Swarm</button>
          {runningCount > 0 && <button onClick={killAllAgents} className="px-1.5 py-0.5 text-[10px] bg-red-500/20 text-red-400 hover:bg-red-500/30 rounded">☠️ Kill All</button>}
        </div>
      </div>

      {/* Error banner */}
      {error && (
        <div className="px-2 py-1 text-[10px] bg-red-500/10 text-red-400 border-b border-red-500/20">
          ⚠️ {error}
        </div>
      )}

      {/* Content */}
      <div className="flex-1 overflow-y-auto">
        {tab === "agents" ? (
          subAgents.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-full text-muted-foreground p-4">
              <span className="text-2xl mb-1">🤖</span>
              <p className="text-xs">No subagents yet</p>
              <p className="text-[10px] mt-0.5">Spawn a subagent or deploy a swarm</p>
            </div>
          ) : (
            <div className="divide-y divide-border">
              {subAgents.map((agent) => {
                const typeCfg = AGENT_TYPE_CONFIG[agent.agent_type] || { icon: "🤖", label: agent.agent_type };
                const isSelected = selectedAgentId === agent.id;
                return (
                  <div key={agent.id} onClick={() => selectAgent(isSelected ? null : agent.id)} className={`flex items-center justify-between p-2 cursor-pointer transition-colors ${isSelected ? "bg-primary/10" : "hover:bg-muted/50"}`}>
                    <div className="flex items-center gap-1.5 min-w-0">
                      <span className="text-sm">{typeCfg.icon}</span>
                      <div className="min-w-0">
                        <div className="text-[10px] font-medium truncate">{agent.name}</div>
                        <div className="flex items-center gap-1 mt-0.5"><StatusBadge status={agent.status} /><PriorityBadge priority={agent.priority} /></div>
                      </div>
                    </div>
                    <div className="flex items-center gap-1.5 flex-shrink-0">
                      <DurationDisplay ms={agent.duration_ms} />
                      {agent.is_live && <span className="w-1.5 h-1.5 rounded-full bg-green-500 animate-pulse" />}
                      {agent.status === "running" && <button onClick={(e) => { e.stopPropagation(); handleKillAgent(agent.id); }} className="px-1 py-0.5 text-[9px] bg-red-500/20 text-red-400 hover:bg-red-500/30 rounded">Kill</button>}
                    </div>
                  </div>
                );
              })}
            </div>
          )
        ) : (
          swarms.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-full text-muted-foreground p-4">
              <span className="text-2xl mb-1">🐝</span>
              <p className="text-xs">No swarms yet</p>
              <p className="text-[10px] mt-0.5">Deploy a swarm to coordinate agents</p>
            </div>
          ) : (
            <div className="divide-y divide-border">
              {swarms.map((swarm) => {
                const stratCfg = STRATEGY_CONFIG[swarm.strategy] || { icon: "🐝", label: swarm.strategy };
                const isSelected = selectedSwarmId === swarm.id;
                return (
                  <div key={swarm.id} onClick={() => selectSwarm(isSelected ? null : swarm.id)} className={`flex items-center justify-between p-2 cursor-pointer transition-colors ${isSelected ? "bg-primary/10" : "hover:bg-muted/50"}`}>
                    <div className="flex items-center gap-1.5 min-w-0">
                      <span className="text-sm">{stratCfg.icon}</span>
                      <div className="min-w-0">
                        <div className="text-[10px] font-medium truncate">🐝 {swarm.name}</div>
                        <div className="flex items-center gap-1 mt-0.5"><StatusBadge status={swarm.status} /><span className="text-[9px] text-muted-foreground">{swarm.completed_count}/{swarm.agent_count}</span></div>
                      </div>
                    </div>
                    <div className="flex items-center gap-1.5 flex-shrink-0">
                      {swarm.status === "running" && <button onClick={(e) => { e.stopPropagation(); handleKillSwarm(swarm.id); }} className="px-1 py-0.5 text-[9px] bg-red-500/20 text-red-400 hover:bg-red-500/30 rounded">Kill</button>}
                    </div>
                  </div>
                );
              })}
            </div>
          )
        )}
      </div>

      {/* Detail panels */}
      {detailAgent && <div className="border-t border-border max-h-[50%] overflow-y-auto"><AgentDetail agent={detailAgent} onClose={() => { selectAgent(null); setDetailAgent(null); }} onKill={handleKillAgent} /></div>}
      {detailSwarm && <div className="border-t border-border max-h-[50%] overflow-y-auto"><SwarmDetail swarm={detailSwarm} onClose={() => { selectSwarm(null); setDetailSwarm(null); }} onKill={handleKillSwarm} /></div>}

      {/* Dialogs */}
      {showSpawn && <SpawnDialog onClose={() => setShowSpawn(false)} onSpawn={spawnAgent} />}
      {showSwarmDeploy && <SwarmDeployDialog onClose={() => setShowSwarmDeploy(false)} onDeploy={deploySwarmAction} />}
    </div>
  );
}
