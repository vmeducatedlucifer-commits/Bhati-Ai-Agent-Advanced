import { Blocks, Boxes, Check, Compass, Github, KeyRound, LayoutGrid, Search, Sparkles, WandSparkles } from "lucide-react";
import { useMemo, useState } from "react";
import { ConnectorsTab } from "@/components/settings/ConnectorsTab";
import { McpTab } from "@/components/settings/McpTab";
import { SkillsTab } from "@/components/settings/SkillsTab";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import { MANUS_CONNECTOR_CATALOG } from "@/components/settings/manusConnectorCatalog";
import type { ManusConnectorCatalogItem } from "@/components/settings/manusConnectorCatalog";
import { ConnectorSetupDialog } from "@/components/settings/ConnectorSetupDialog";

type Section = "discover" | "connectors" | "mcp" | "skills";

const SECTIONS: Array<{
  id: Section;
  label: string;
  eyebrow: string;
  description: string;
  icon: typeof Blocks;
}> = [
  { id: "discover", label: "Discover", eyebrow: "Marketplace", description: "Find capabilities for your agent", icon: Compass },
  { id: "connectors", label: "Connectors", eyebrow: "Accounts", description: "Link the tools you already use", icon: Blocks },
  { id: "mcp", label: "MCP servers", eyebrow: "Tools", description: "Install local or hosted tool servers", icon: Boxes },
  { id: "skills", label: "Agent skills", eyebrow: "Instructions", description: "Add reusable expert workflows", icon: WandSparkles },
];

const CATALOG = [
  { section: "connectors" as const, title: "GitHub", detail: "Repositories, issues, pull requests, and workspace sync", tags: ["OAuth", "Developer"] , icon: Github },
  { section: "connectors" as const, title: "Vercel + Render", detail: "Preview, deploy, and monitor your web projects", tags: ["Deploy", "Connected apps"], icon: Sparkles },
  { section: "mcp" as const, title: "MCP Registry", detail: "Discover community servers that add tools to every run", tags: ["Local", "Hosted"], icon: Boxes },
  { section: "skills" as const, title: "Skill marketplace", detail: "Install tested SKILL.md packs for research, coding, and operations", tags: ["Reusable", "Versioned"], icon: WandSparkles },
];

export function MarketplaceTab() {
  const [section, setSection] = useState<Section>("discover");
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState("all");
  const [setupItem, setSetupItem] = useState<ManusConnectorCatalogItem | null>(null);
  const filteredCatalog = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return CATALOG.filter((item) => !needle || `${item.title} ${item.detail} ${item.tags.join(" ")}`.toLowerCase().includes(needle));
  }, [query]);
  const filteredConnectors = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return MANUS_CONNECTOR_CATALOG.filter((item) => (category === "all" || item.category === category) && (!needle || `${item.name} ${item.description} ${item.category}`.toLowerCase().includes(needle)));
  }, [category, query]);

  return (
    <div className="space-y-5">
      <div className="rounded-2xl border border-primary/25 bg-gradient-to-br from-primary/10 via-surface to-violet-500/10 p-4 sm:p-5">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
          <div className="flex gap-3">
            <div className="flex size-10 shrink-0 items-center justify-center rounded-2xl bg-primary text-primary-foreground shadow-lg shadow-primary/20">
              <LayoutGrid className="size-5" />
            </div>
            <div>
              <p className="flex items-center gap-2 text-base font-semibold tracking-tight">Marketplace <span className="rounded-full border border-primary/20 bg-primary/10 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider text-primary">Unified</span></p>
              <p className="mt-1 max-w-2xl text-[12.5px] leading-relaxed text-muted-foreground">Extend your agent with connected apps, MCP tools, and reusable skills. Install once, review permissions, and manage everything from one place.</p>
            </div>
          </div>
          <div className="relative w-full sm:w-60">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
            <Input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search marketplace" className="h-8 bg-surface/70 pl-8 text-xs" />
          </div>
        </div>
        <div className="mt-4 grid gap-2 text-[11.5px] text-muted-foreground sm:grid-cols-3">
          <div className="flex items-center gap-2 rounded-xl border border-border/60 bg-surface/55 px-3 py-2"><KeyRound className="size-3.5 text-primary" /> Encrypted credentials</div>
          <div className="flex items-center gap-2 rounded-xl border border-border/60 bg-surface/55 px-3 py-2"><Check className="size-3.5 text-emerald-500" /> Verify before use</div>
          <div className="flex items-center gap-2 rounded-xl border border-border/60 bg-surface/55 px-3 py-2"><Sparkles className="size-3.5 text-violet-400" /> Available to the agent</div>
        </div>
      </div>

      <div className="grid gap-1 rounded-2xl border border-border bg-muted/45 p-1 sm:grid-cols-4">
        {SECTIONS.map((item) => {
          const Icon = item.icon;
          return (
            <button key={item.id} type="button" onClick={() => setSection(item.id)} className={cn("rounded-xl px-3 py-2.5 text-left transition-all", section === item.id ? "bg-surface shadow-sm" : "text-muted-foreground hover:bg-surface/60 hover:text-foreground")}>
              <span className="flex items-center gap-2 text-[12.5px] font-medium"><Icon className="size-3.5" />{item.label}</span>
              <span className="mt-0.5 block truncate text-[10.5px]">{item.description}</span>
            </button>
          );
        })}
      </div>

      {section === "discover" ? (
        <div className="space-y-3">
          <div className="flex items-end justify-between"><div><h3 className="text-sm font-semibold">Start with a capability</h3><p className="text-[12px] text-muted-foreground">Choose a category to explore the full install and management experience.</p></div><span className="text-[11px] text-muted-foreground">{filteredCatalog.length} collections</span></div>
          <div className="grid gap-3 sm:grid-cols-2">
            {filteredCatalog.map((item) => {
              const Icon = item.icon;
              return <button key={item.title} type="button" onClick={() => setSection(item.section)} className="lift rounded-2xl border border-border bg-surface p-4 text-left hover:border-primary/35 hover:bg-primary/[.03]"><div className="flex items-start gap-3"><span className="flex size-9 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary"><Icon className="size-4" /></span><span className="min-w-0"><span className="block text-sm font-semibold">{item.title}</span><span className="mt-1 block text-[12px] leading-relaxed text-muted-foreground">{item.detail}</span><span className="mt-2 flex flex-wrap gap-1.5">{item.tags.map((tag) => <span key={tag} className="rounded-full bg-muted px-2 py-0.5 text-[10px] text-muted-foreground">{tag}</span>)}</span></span></div></button>;
            })}
          </div>
          <p className="rounded-xl border border-dashed border-border px-3 py-3 text-center text-[11.5px] text-muted-foreground">Search, install, enable, update, or remove extensions without leaving this marketplace.</p>
          <section className="space-y-3 border-t border-border pt-5">
            <div className="flex items-end justify-between gap-3"><div><h3 className="text-sm font-semibold">Manus connector catalog</h3><p className="text-[12px] text-muted-foreground">The public catalog is discoverable here; verified Rawal integrations can be connected directly.</p></div><span className="shrink-0 text-[11px] text-muted-foreground">{MANUS_CONNECTOR_CATALOG.length} connectors</span></div>
            <div className="flex flex-wrap gap-1.5">
              {["all", "productivity", "development", "ai", "automation", "growth", "media", "commerce", "data", "browser"].map((value) => <button key={value} type="button" onClick={() => setCategory(value)} className={cn("rounded-full border px-2.5 py-1 text-[10.5px] capitalize transition-colors", category === value ? "border-primary/40 bg-primary/10 text-primary" : "border-border text-muted-foreground hover:text-foreground")}>{value}</button>)}
            </div>
            <div className="grid gap-2 sm:grid-cols-2">
              {filteredConnectors.map((item) => <button key={item.id} type="button" onClick={() => setSetupItem(item)} className="lift w-full rounded-xl border border-border bg-surface px-3 py-2.5 text-left hover:border-primary/35 hover:bg-primary/[.03]"><div className="flex items-start gap-2"><div className="min-w-0 flex-1"><p className="flex flex-wrap items-center gap-1.5 text-[12.5px] font-medium">{item.name}<span className="rounded-full bg-muted px-1.5 py-0.5 text-[9.5px] text-muted-foreground">{item.auth}</span></p><p className="mt-0.5 text-[11px] leading-relaxed text-muted-foreground">{item.description}</p><p className="mt-1 text-[10.5px] text-primary">Click to connect</p></div>{item.implemented ? <span title="Direct connector ready" className="rounded-full bg-emerald-500/10 px-1.5 py-0.5 text-[9.5px] text-emerald-600 dark:text-emerald-400">Ready</span> : <span title="Catalog entry; connect through MCP/custom setup" className="rounded-full bg-amber-500/10 px-1.5 py-0.5 text-[9.5px] text-amber-600 dark:text-amber-400">MCP setup</span>}</div></button>)}
            </div>
          </section>
        </div>
      ) : null}

      {section === "connectors" ? (
        <div className="space-y-5">
          <section className="space-y-2">
            <div><h3 className="text-sm font-semibold">Developer and deployment apps</h3><p className="text-[12px] text-muted-foreground">GitHub, Vercel, Render, model providers, and other build tools.</p></div>
            <ConnectorsTab kind="general" />
          </section>
          <section className="space-y-2 border-t border-border pt-5">
            <div><h3 className="text-sm font-semibold">Communication and social apps</h3><p className="text-[12px] text-muted-foreground">Connect messaging and publishing accounts used by your workflows.</p></div>
            <ConnectorsTab kind="social" />
          </section>
        </div>
      ) : null}
      {section === "mcp" ? <McpTab /> : null}
      {section === "skills" ? <SkillsTab /> : null}
      <ConnectorSetupDialog item={setupItem} open={Boolean(setupItem)} onOpenChange={(open) => { if (!open) setSetupItem(null); }} />
    </div>
  );
}

export default MarketplaceTab;

export const MARKETPLACE_SECTIONS = SECTIONS;
