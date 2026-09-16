import { Download, Globe, Loader2, Plug, Plus, RotateCw, Store, Trash2, X } from "lucide-react";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Field, Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import type { DirectoryServer, McpServerInfo, RegistryServer } from "@/types";

interface Draft {
  name: string;
  transport: "stdio" | "sse" | "http";
  command: string;
  args: string;
  url: string;
  env: string;
}

const EMPTY: Draft = { name: "", transport: "stdio", command: "", args: "", url: "", env: "" };

/** Curated community servers — 1-click fill into the add form. */
const MARKETPLACE: { name: string; blurb: string; draft: Draft }[] = [
  {
    name: "filesystem",
    blurb: "Secure file ops rooted at a folder you choose",
    draft: { name: "filesystem", transport: "stdio", command: "npx", args: "-y @modelcontextprotocol/server-filesystem /workspace", url: "", env: "" },
  },
  {
    name: "github",
    blurb: "Repos, issues, PRs via your token",
    draft: { name: "github", transport: "stdio", command: "npx", args: "-y @modelcontextprotocol/server-github", url: "", env: "GITHUB_PERSONAL_ACCESS_TOKEN=ghp_…" },
  },
  {
    name: "brave-search",
    blurb: "Web search grounding for the agent",
    draft: { name: "brave-search", transport: "stdio", command: "npx", args: "-y @modelcontextprotocol/server-brave-search", url: "", env: "BRAVE_API_KEY=…" },
  },
  {
    name: "sqlite",
    blurb: "Query any sqlite db file read-only",
    draft: { name: "sqlite", transport: "stdio", command: "uvx", args: "mcp-server-sqlite --db-path /workspace/app.db", url: "", env: "" },
  },
  {
    name: "puppeteer",
    blurb: "Headless browser automation + screenshots",
    draft: { name: "puppeteer", transport: "stdio", command: "npx", args: "-y @modelcontextprotocol/server-puppeteer", url: "", env: "" },
  },
];

function parseEnv(raw: string): Record<string, string> {
  const out: Record<string, string> = {};
  for (const line of raw.split("\n")) {
    const index = line.indexOf("=");
    if (index > 0) out[line.slice(0, index).trim()] = line.slice(index + 1).trim();
  }
  return out;
}

export function McpTab() {
  const [servers, setServers] = useState<McpServerInfo[]>([]);
  const [presets, setPresets] = useState<Record<string, unknown>[]>([]);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [regQuery, setRegQuery] = useState("");
  const [regResults, setRegResults] = useState<RegistryServer[]>([]);
  const [regSearched, setRegSearched] = useState(false);
  const [regBusy, setRegBusy] = useState<string | null>(null);
  const [dirQuery, setDirQuery] = useState("");
  const [dirResults, setDirResults] = useState<DirectoryServer[]>([]);
  const [dirSearched, setDirSearched] = useState(false);
  const [dirBusy, setDirBusy] = useState<string | null>(null);

  const load = async () => setServers(await api.listMcp());

  // Server boot (npx downloads) now happens in the background: keep
  // refreshing until nothing is "starting" so the real state appears
  // without the user having to close and reopen Settings.
  const waitForSettled = async () => {
    for (let i = 0; i < 25; i++) {
      await new Promise((resolve) => window.setTimeout(resolve, 3000));
      try {
        const next = await api.listMcp();
        setServers(next);
        if (!next.some((s) => s.status === "starting")) return;
      } catch {
        return;
      }
    }
  };

  useEffect(() => {
    void load();
    void api.mcpPresets().then(setPresets);
  }, []);

  const searchRegistry = async () => {
    setRegBusy("search");
    setError("");
    try {
      const res = await api.mcpRegistry(regQuery.trim(), 30, 0);
      setRegResults(res.servers);
      setRegSearched(true);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Registry unreachable");
    } finally {
      setRegBusy(null);
    }
  };

  const installFromRegistry = async (name: string) => {
    setRegBusy(name);
    setError("");
    try {
      await api.mcpRegistryInstall(name);
      await load();
      void waitForSettled();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Install failed");
    } finally {
      setRegBusy(null);
    }
  };

  const searchDirectory = async () => {
    setDirBusy("search");
    setError("");
    try {
      const res = await api.mcpDirectory(dirQuery.trim(), 30);
      setDirResults(res.servers);
      setDirSearched(true);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Directory unreachable");
    } finally {
      setDirBusy(null);
    }
  };

  const installFromDirectory = async (slug: string) => {
    setDirBusy(slug);
    setError("");
    try {
      await api.mcpDirectoryInstall(slug);
      await load();
      void waitForSettled();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Install failed");
    } finally {
      setDirBusy(null);
    }
  };

  const add = async () => {
    if (!draft) return;
    setBusy(true);
    setError("");
    try {
      await api.addMcp({
        name: draft.name,
        transport: draft.transport,
        command: draft.command,
        args: draft.args.trim() ? draft.args.trim().split(/\s+/) : [],
        url: draft.url,
        env: parseEnv(draft.env),
      });
      setDraft(null);
      await load();
      void waitForSettled();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Failed to start");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-4">
      <p className="text-[12.5px] text-muted-foreground">
        Model Context Protocol servers add their tools to the agent. stdio servers run as a
        subprocess of the backend; SSE and HTTP servers connect over the network.
      </p>

      {/* official registry */}
      <div className="rounded-xl border border-primary/25 bg-primary/5 p-3.5">
        <p className="mb-1 flex items-center gap-1.5 text-[13px] font-medium">
          <Plug className="size-4 text-primary" />
          Official MCP Registry
          <span className="font-normal text-muted-foreground">· registry.modelcontextprotocol.io</span>
        </p>
        <div className="mb-2.5 flex gap-2">
          <Input
            value={regQuery}
            onChange={(e) => setRegQuery(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && void searchRegistry()}
            placeholder="Search official servers (notion, filesystem, fetch…)"
            className="h-8 flex-1 text-xs"
          />
          <Button size="sm" variant="outline" disabled={regBusy !== null} onClick={() => void searchRegistry()}>
            {regBusy === "search" ? <Loader2 className="size-3.5 animate-spin" /> : "Search"}
          </Button>
        </div>
        {error ? <p className="mb-2 text-[12px] text-danger animate-message-in">{error}</p> : null}
        {regResults.length > 0 ? (
          <ul className="max-h-72 space-y-1.5 overflow-y-auto scrollbar-thin">
            {regResults.map((server) => (
              <li key={server.name} className="rounded-lg border border-border bg-surface px-3 py-2">
                <div className="flex items-center gap-2">
                  <div className="min-w-0 flex-1">
                    <p className="truncate font-mono text-[12px]">{server.name}</p>
                    <p className="line-clamp-1 text-[11.5px] text-muted-foreground">{server.description || "No description"}</p>
                    <p className="mt-0.5 flex flex-wrap gap-1">
                      {server.version ? <Badge tone="muted">v{server.version}</Badge> : null}
                      {server.transports.map((t) => (
                        <Badge key={t} tone="primary">{t}</Badge>
                      ))}
                    </p>
                  </div>
                  <Button size="xs" disabled={regBusy === server.name} onClick={() => void installFromRegistry(server.name)}>
                    {regBusy === server.name ? <Loader2 className="size-3 animate-spin" /> : <Download className="size-3" />}
                    {regBusy === server.name ? "Installing…" : "Install"}
                  </Button>
                </div>
              </li>
            ))}
          </ul>
        ) : regSearched ? (
          <p className="py-2 text-center text-[12px] text-muted-foreground">No registry matches — try another search.</p>
        ) : null}
      </div>

      {/* second marketplace: hosted servers, no local install */}
      <div className="rounded-xl border border-primary/25 bg-primary/5 p-3.5">
        <p className="mb-1 flex items-center gap-1.5 text-[13px] font-medium">
          <Globe className="size-4 text-primary" />
          Hosted directory
          <span className="font-normal text-muted-foreground">· mcpservers.org</span>
        </p>
        <p className="mb-2.5 text-[12px] text-muted-foreground">
          Official remote servers (Notion, Linear, Stripe…) — connect over HTTP, nothing to download.
        </p>
        <div className="mb-2.5 flex gap-2">
          <Input
            value={dirQuery}
            onChange={(e) => setDirQuery(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && void searchDirectory()}
            placeholder="Search hosted servers (notion, linear, stripe…)"
            className="h-8 flex-1 text-xs"
          />
          <Button size="sm" variant="outline" disabled={dirBusy === "search"} onClick={() => void searchDirectory()}>
            {dirBusy === "search" ? <Loader2 className="size-3.5 animate-spin" /> : "Search"}
          </Button>
        </div>
        {dirResults.length > 0 ? (
          <ul className="max-h-72 space-y-1.5 overflow-y-auto scrollbar-thin">
            {dirResults.map((server) => (
              <li key={server.slug} className="rounded-lg border border-border bg-surface px-3 py-2">
                <div className="flex items-center gap-2">
                  <div className="min-w-0 flex-1">
                    <p className="truncate font-mono text-[12px]">{server.name}</p>
                    <p className="line-clamp-1 text-[11.5px] text-muted-foreground">{server.description || "No description"}</p>
                    <p className="mt-0.5">
                      <Badge tone="primary">hosted</Badge>
                    </p>
                  </div>
                  <Button size="xs" disabled={dirBusy === server.slug} onClick={() => void installFromDirectory(server.slug)}>
                    {dirBusy === server.slug ? <Loader2 className="size-3 animate-spin" /> : <Download className="size-3" />}
                    {dirBusy === server.slug ? "Installing…" : "Install"}
                  </Button>
                </div>
              </li>
            ))}
          </ul>
        ) : dirSearched ? (
          <p className="py-2 text-center text-[12px] text-muted-foreground">No directory matches — try another search.</p>
        ) : null}
      </div>

      <div className="space-y-2">
        {servers.map((server) => (
          <div key={server.id} className="rounded-xl border border-border bg-surface p-3">
            <div className="flex items-center gap-3">
              <div className="min-w-0 flex-1">
                <p className="flex items-center gap-2 text-[13px] font-medium">
                  {server.name}
                  <Badge
                    tone={
                      server.status === "running" ? "success" : server.status === "error" ? "danger" : "muted"
                    }
                  >
                    {server.status}
                  </Badge>
                  <Badge tone="muted">{server.transport}</Badge>
                </p>
                <p className="truncate font-mono text-[11px] text-muted-foreground">
                  {server.transport === "stdio"
                    ? `${server.command} ${server.args.join(" ")}`
                    : server.url}
                </p>
                {server.error ? <p className="mt-1 text-[11.5px] text-danger">{server.error}</p> : null}
                {server.tools.length > 0 && (
                  <div className="mt-1.5 flex flex-wrap gap-1">
                    {server.tools.slice(0, 12).map((tool) => (
                      <span
                        key={tool.name}
                        title={tool.description}
                        className="rounded bg-muted px-1.5 py-0.5 font-mono text-[10.5px] text-muted-foreground"
                      >
                        {tool.original}
                      </span>
                    ))}
                    {server.tools.length > 12 ? (
                      <span className="text-[10.5px] text-muted-foreground">
                        +{server.tools.length - 12} more
                      </span>
                    ) : null}
                  </div>
                )}
              </div>

              <Button
                variant="ghost"
                size="icon-sm"
                title="Restart"
                onClick={async () => {
                  await api.restartMcp(server.name);
                  await load();
                  void waitForSettled();
                }}
              >
                <RotateCw className="size-3.5" />
              </Button>
              <Button
                variant="ghost"
                size="icon-sm"
                onClick={async () => {
                  if (!confirm(`Remove ${server.name}?`)) return;
                  await api.removeMcp(server.name);
                  await load();
                }}
              >
                <Trash2 className="size-3.5 text-danger" />
              </Button>
            </div>
          </div>
        ))}
      </div>

      <div>
        <p className="mb-1.5 flex items-center gap-1.5 text-[12px] font-medium">
          <Store className="size-3.5 text-primary" />
          Community marketplace — 1-click install
        </p>
        <div className="grid gap-2 sm:grid-cols-2">
          {MARKETPLACE.map((item) => (
            <button
              key={item.name}
              type="button"
              onClick={() => setDraft({ ...item.draft })}
              className="lift rounded-xl border border-border bg-surface p-3 text-left"
            >
              <p className="font-mono text-[12.5px] font-medium">{item.name}</p>
              <p className="mt-0.5 text-[11.5px] text-muted-foreground">{item.blurb}</p>
            </button>
          ))}
        </div>
      </div>

      {draft ? (
        <div className="space-y-3 rounded-xl border border-border bg-surface p-3.5">
          <div className="flex items-center justify-between">
            <p className="text-[13px] font-medium">Add MCP server</p>
            <Button variant="ghost" size="icon-sm" onClick={() => setDraft(null)}>
              <X className="size-3.5" />
            </Button>
          </div>

          <div className="flex flex-wrap gap-1.5">
            {presets.map((preset) => (
              <button
                key={String(preset.name)}
                type="button"
                onClick={() =>
                  setDraft({
                    ...EMPTY,
                    name: String(preset.name),
                    transport: preset.transport as Draft["transport"],
                    command: String(preset.command ?? ""),
                    args: ((preset.args as string[]) ?? []).join(" "),
                  })
                }
                className="rounded-full border border-border px-2.5 py-1 text-[11.5px] text-muted-foreground transition-colors hover:border-primary/40 hover:text-foreground"
              >
                {String(preset.name)}
              </button>
            ))}
          </div>

          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Name" hint="Tools appear as mcp__name__tool">
              <Input
                value={draft.name}
                onChange={(e) => setDraft({ ...draft, name: e.target.value.replace(/[^a-zA-Z0-9_-]/g, "") })}
              />
            </Field>
            <Field label="Transport">
              <select
                value={draft.transport}
                onChange={(e) => setDraft({ ...draft, transport: e.target.value as Draft["transport"] })}
                className="h-9 w-full rounded-lg border border-input bg-surface px-3 text-sm"
              >
                <option value="stdio">stdio (subprocess)</option>
                <option value="sse">SSE</option>
                <option value="http">Streamable HTTP</option>
              </select>
            </Field>
          </div>

          {draft.transport === "stdio" ? (
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label="Command">
                <Input
                  value={draft.command}
                  placeholder="npx"
                  onChange={(e) => setDraft({ ...draft, command: e.target.value })}
                />
              </Field>
              <Field label="Arguments">
                <Input
                  value={draft.args}
                  placeholder="-y @modelcontextprotocol/server-filesystem /workspace"
                  onChange={(e) => setDraft({ ...draft, args: e.target.value })}
                />
              </Field>
            </div>
          ) : (
            <Field label="URL">
              <Input
                value={draft.url}
                placeholder="https://mcp.example.com/sse"
                onChange={(e) => setDraft({ ...draft, url: e.target.value })}
              />
            </Field>
          )}

          <Field label="Environment" hint="One KEY=value per line">
            <textarea
              value={draft.env}
              onChange={(e) => setDraft({ ...draft, env: e.target.value })}
              rows={3}
              placeholder="GITHUB_TOKEN=ghp_…"
              className="w-full rounded-lg border border-input bg-surface px-3 py-2 font-mono text-[12.5px]"
            />
          </Field>

          {error ? <p className="text-[12.5px] text-danger">{error}</p> : null}

          <Button size="sm" disabled={busy || !draft.name} onClick={() => void add()}>
            {busy ? <Loader2 className="size-3.5 animate-spin" /> : null}
            Add and start
          </Button>
        </div>
      ) : (
        <Button variant="outline" size="sm" onClick={() => setDraft({ ...EMPTY })}>
          <Plus className="size-4" />
          Add MCP server
        </Button>
      )}
    </div>
  );
}
