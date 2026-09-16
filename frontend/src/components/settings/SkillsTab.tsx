import { BookOpen, ClipboardPaste, Download, Eye, Github, Link2, PackagePlus, Store, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { activeProject } from "@/lib/store";
import { useStore } from "@/lib/store";
import { cn } from "@/lib/utils";
import type { GithubSkill, MarketplaceSkill, SkillInfo } from "@/types";

const SOURCE_TONE: Record<string, "primary" | "success" | "warning" | "muted"> = {
  marketplace: "primary",
  github: "success",
  url: "warning",
  paste: "muted",
  "claude-dir": "muted",
  flat: "muted",
};

export function SkillsTab() {
  const project = useStore(activeProject);
  const [skills, setSkills] = useState<SkillInfo[]>([]);
  const [method, setMethod] = useState<"marketplace" | "github" | "url" | "paste">("marketplace");
  const [market, setMarket] = useState<MarketplaceSkill[]>([]);
  const [marketQuery, setMarketQuery] = useState("");
  const [repo, setRepo] = useState("");
  const [scanned, setScanned] = useState<GithubSkill[]>([]);
  const [url, setUrl] = useState("");
  const [pasteName, setPasteName] = useState("");
  const [pasteBody, setPasteBody] = useState("");
  const [viewing, setViewing] = useState<{ name: string; body: string } | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState("");

  const load = async () => {
    if (!project) return;
    setSkills(await api.listSkills(project.id).catch(() => []));
  };
  const loadMarket = async (q = "") => {
    setMarket(await api.skillMarketplace(q).catch(() => []));
  };

  useEffect(() => {
    void load();
    void loadMarket();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [project?.id]);

  useEffect(() => {
    const timer = window.setTimeout(() => void loadMarket(marketQuery), 400);
    return () => window.clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [marketQuery]);

  if (!project) return <p className="text-[13px] text-muted-foreground">Create a project first.</p>;

  const refresh = async () => {
    await load();
    await loadMarket(marketQuery);
  };

  const run = async (key: string, fn: () => Promise<unknown>) => {
    setBusy(key);
    setError("");
    try {
      await fn();
      await refresh();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Failed");
    } finally {
      setBusy(null);
    }
  };

  const installed = new Set(skills.map((s) => s.name));

  return (
    <div className="space-y-5">
      <div>
        <h3 className="text-sm font-semibold tracking-tight">Agent Skills</h3>
        <p className="text-[12.5px] text-muted-foreground">
          Claude/OpenClaw-compatible <code className="rounded bg-muted px-1 font-mono">SKILL.md</code> packs.
          The agent always sees the skill index and auto-loads full instructions when relevant — no manual wiring.
        </p>
      </div>

      {/* installed */}
      <div className="space-y-2">
        <p className="text-[12.5px] font-medium">
          Installed <Badge tone="muted" className="ml-1">{skills.length}</Badge>
        </p>
        {skills.length === 0 ? (
          <p className="rounded-xl border border-dashed border-border px-3 py-4 text-center text-[12.5px] text-muted-foreground">
            No skills yet — install one below and the agent starts using it automatically.
          </p>
        ) : (
          <ul className="space-y-1.5">
            {skills.map((skill) => (
              <li key={skill.name} className={cn("rounded-xl border border-border bg-surface px-3 py-2", !skill.enabled && "opacity-55")}>
                <div className="flex items-center gap-2">
                  <BookOpen className="size-3.5 shrink-0 text-primary" />
                  <p className="min-w-0 flex-1 truncate font-mono text-[12.5px]">{skill.name}</p>
                  <Badge tone={SOURCE_TONE[skill.source] ?? "muted"}>{skill.source}</Badge>
                  <button
                    type="button"
                    title={skill.enabled ? "Disable" : "Enable"}
                    onClick={() => void run(`toggle-${skill.name}`, () => api.toggleSkill(project.id, skill.name, !skill.enabled))}
                    className={cn(
                      "relative h-5 w-9 shrink-0 rounded-full transition-colors",
                      skill.enabled ? "bg-primary" : "bg-muted-foreground/35",
                    )}
                  >
                    <span className={cn("absolute top-0.5 size-4 rounded-full bg-white shadow transition-all", skill.enabled ? "left-[18px]" : "left-0.5")} />
                  </button>
                  <button
                    type="button"
                    title="View instructions"
                    onClick={async () => {
                      const full = await api.getSkill(project.id, skill.name).catch(() => null);
                      if (full) setViewing({ name: full.name, body: full.body });
                    }}
                    className="rounded p-1 text-muted-foreground hover:text-foreground"
                  >
                    <Eye className="size-3.5" />
                  </button>
                  <button
                    type="button"
                    title="Delete skill"
                    onClick={() => {
                      if (confirm(`Delete skill "${skill.name}"?`)) void run(`del-${skill.name}`, () => api.deleteSkill(project.id, skill.name));
                    }}
                    className="rounded p-1 text-muted-foreground hover:text-danger"
                  >
                    <Trash2 className="size-3.5" />
                  </button>
                </div>
                <p className="mt-0.5 line-clamp-2 text-[12px] text-muted-foreground">{skill.description}</p>
              </li>
            ))}
          </ul>
        )}
        {viewing ? (
          <div className="rounded-xl border border-primary/30 bg-primary/5 p-3 animate-message-in">
            <div className="mb-1.5 flex items-center justify-between">
              <p className="font-mono text-[12.5px] font-medium">{viewing.name}/SKILL.md</p>
              <button type="button" onClick={() => setViewing(null)} className="text-[12px] text-muted-foreground hover:text-foreground">
                Close
              </button>
            </div>
            <pre className="scrollbar-thin max-h-64 overflow-y-auto whitespace-pre-wrap font-mono text-[11.5px] leading-relaxed">{viewing.body}</pre>
          </div>
        ) : null}
      </div>

      {/* add */}
      <div>
        <div className="mb-2.5 flex gap-1 rounded-lg bg-muted p-1">
          {(
            [
              ["marketplace", "Marketplace", Store],
              ["github", "GitHub", Github],
              ["url", "URL", Link2],
              ["paste", "Paste", ClipboardPaste],
            ] as const
          ).map(([key, label, Icon]) => (
            <button
              key={key}
              type="button"
              onClick={() => setMethod(key)}
              className={cn(
                "flex flex-1 items-center justify-center gap-1.5 rounded-md px-2 py-1.5 text-[12.5px] font-medium transition-colors",
                method === key ? "bg-surface text-foreground shadow-sm" : "text-muted-foreground",
              )}
            >
              <Icon className="size-3.5" />
              {label}
            </button>
          ))}
        </div>

        {method === "marketplace" && (
          <div className="space-y-2">
            <Input value={marketQuery} onChange={(e) => setMarketQuery(e.target.value)} placeholder="Search skills (pdf, testing, frontend…)" className="h-8 text-xs" />
            <ul className="space-y-1.5">
              {market.map((m) => (
                <li key={m.id} className="rounded-xl border border-border bg-surface p-3">
                  <div className="flex items-center gap-2">
                    <div className="min-w-0 flex-1">
                      <p className="flex flex-wrap items-center gap-1.5 font-mono text-[12.5px]">
                        {m.name}
                        <Badge tone="primary">{m.source}</Badge>
                        {m.live ? <Badge tone="muted">live</Badge> : null}
                      </p>
                      <p className="mt-0.5 line-clamp-2 text-[12px] text-muted-foreground">{m.description}</p>
                    </div>
                    {installed.has(m.name) ? (
                      <Badge tone="success">installed</Badge>
                    ) : (
                      <Button size="xs" disabled={busy === `mkt-${m.id}`} onClick={() => void run(`mkt-${m.id}`, () => api.installMarketplaceSkill(project.id, m.id))}>
                        <Download className="size-3" />
                        {busy === `mkt-${m.id}` ? "Installing…" : "Install"}
                      </Button>
                    )}
                  </div>
                </li>
              ))}
              {market.length === 0 ? (
                <p className="py-3 text-center text-[12.5px] text-muted-foreground">No matches — try another search.</p>
              ) : null}
            </ul>
          </div>
        )}

        {method === "github" && (
          <div className="space-y-2 rounded-xl border border-border bg-surface p-3">
            <p className="text-[12px] text-muted-foreground">
              Any public repo — <code className="font-mono">owner/repo</code>, <code className="font-mono">owner/repo@branch</code> or a subpath. Works with OpenClaw, Claude and community skill repos.
            </p>
            <div className="flex gap-2">
              <Input value={repo} onChange={(e) => setRepo(e.target.value)} placeholder="anthropics/skills" className="h-8 flex-1 font-mono text-xs" />
              <Button
                size="sm"
                variant="outline"
                disabled={!repo.trim() || busy === "scan"}
                onClick={() => void run("scan", async () => setScanned(await api.scanGithubSkills(project.id, repo.trim())))}
              >
                Scan
              </Button>
            </div>
            {scanned.length > 0 && (
              <>
                <Button
                  size="sm"
                  disabled={busy === "install-all"}
                  onClick={() => void run("install-all", () => api.installGithubSkills(project.id, repo.trim()))}
                >
                  <PackagePlus className="size-3.5" />
                  {busy === "install-all" ? "Installing…" : `Install all (${scanned.length})`}
                </Button>
                <ul className="space-y-1.5">
                  {scanned.map((s) => (
                    <li key={s.path} className="flex items-center gap-2 rounded-lg border border-border px-3 py-2">
                      <div className="min-w-0 flex-1">
                        <p className="truncate font-mono text-[12px]">{s.name || s.path}</p>
                        <p className="truncate text-[11px] text-muted-foreground">{s.description || s.path}</p>
                      </div>
                      <Button
                        size="xs"
                        variant="outline"
                        disabled={busy === `gh-${s.path}`}
                        onClick={() => void run(`gh-${s.path}`, () => api.installGithubSkills(project.id, repo.trim(), [s.path]))}
                      >
                        {busy === `gh-${s.path}` ? "Installing…" : "Install"}
                      </Button>
                    </li>
                  ))}
                </ul>
              </>
            )}
          </div>
        )}

        {method === "url" && (
          <div className="space-y-2 rounded-xl border border-border bg-surface p-3">
            <p className="text-[12px] text-muted-foreground">
              Raw <code className="font-mono">SKILL.md</code> URL, GitHub blob link, repo page, or a <code className="font-mono">.zip</code> of skills.
            </p>
            <div className="flex gap-2">
              <Input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://…/SKILL.md" className="h-8 flex-1 font-mono text-xs" />
              <Button
                size="sm"
                disabled={!url.trim() || busy === "url"}
                onClick={() => void run("url", async () => {
                  await api.installSkillUrl(project.id, url.trim());
                  setUrl("");
                })}
              >
                {busy === "url" ? "Installing…" : "Install"}
              </Button>
            </div>
          </div>
        )}

        {method === "paste" && (
          <div className="space-y-2 rounded-xl border border-border bg-surface p-3">
            <Input value={pasteName} onChange={(e) => setPasteName(e.target.value)} placeholder="Skill name (e.g. my-workflow)" className="h-8 font-mono text-xs" />
            <textarea
              value={pasteBody}
              onChange={(e) => setPasteBody(e.target.value)}
              rows={8}
              placeholder="Paste SKILL.md here (frontmatter optional — generated if missing)…"
              className="scrollbar-thin w-full rounded-lg border border-input bg-surface px-3 py-2 font-mono text-[12px] focus:outline-none"
            />
            <Button
              size="sm"
              disabled={!pasteName.trim() || !pasteBody.trim() || busy === "paste"}
              onClick={() => void run("paste", async () => {
                await api.installSkillPaste(project.id, { name: pasteName.trim(), content: pasteBody });
                setPasteName("");
                setPasteBody("");
              })}
            >
              {busy === "paste" ? "Saving…" : "Save skill"}
            </Button>
          </div>
        )}

        {error ? <p className="text-[12.5px] text-danger animate-message-in">{error}</p> : null}
      </div>
    </div>
  );
}
