import { Cloud, Cpu, Github, Loader2, MonitorDown, Save, Sparkles } from "lucide-react";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Field, Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import type { SandboxConfig } from "@/types";

const BACKENDS = [
  {
    id: "auto",
    icon: Sparkles,
    title: "Auto",
    desc: "Docker when available, otherwise the deploy machine itself.",
  },
  {
    id: "local",
    icon: MonitorDown,
    title: "Local",
    desc: "Run on the machine where the agent is deployed. Fastest, no isolation.",
  },
  {
    id: "docker",
    icon: Cpu,
    title: "Docker",
    desc: "Isolated container per chat. Needs a Docker daemon on the host.",
  },
  {
    id: "superserve",
    icon: Cloud,
    title: "Superserve cloud",
    desc: "Firecracker microVMs in the cloud from a warm pool. Needs your API key.",
  },
  {
    id: "github",
    icon: Github,
    title: "GitHub Actions",
    desc: "Free cloud runners in your repo. Minutes per command — best for heavy background jobs.",
  },
] as const;

export function SandboxTab() {
  const [config, setConfig] = useState<SandboxConfig | null>(null);
  const [backend, setBackend] = useState("auto");
  const [apiKey, setApiKey] = useState("");
  const [template, setTemplate] = useState("superserve/base");
  const [poolSize, setPoolSize] = useState(5);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);

  const load = async () => {
    const current = await api.sandboxConfig().catch(() => null);
    if (!current) return;
    setConfig(current);
    setBackend(current.backend);
    setTemplate(current.superserve_template);
    setPoolSize(current.pool_size);
  };

  useEffect(() => {
    void load();
  }, []);

  const save = async () => {
    setBusy(true);
    setError("");
    setSaved(false);
    try {
      const updated = await api.saveSandboxConfig({
        backend,
        superserve_api_key: apiKey.trim() || undefined,
        superserve_template: backend === "superserve" ? template.trim() || undefined : undefined,
        pool_size: backend === "superserve" ? poolSize : undefined,
      });
      setConfig(updated);
      setApiKey("");
      setSaved(true);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Save failed");
    } finally {
      setBusy(false);
    }
  };

  if (!config) return <p className="text-[13px] text-muted-foreground">Loading…</p>;

  return (
    <div className="space-y-5">
      <div>
        <h3 className="text-sm font-semibold tracking-tight">Sandbox</h3>
        <p className="text-[12.5px] text-muted-foreground">
          Where the agent runs code. Currently active:{" "}
          <Badge tone="primary">{config.effective_backend}</Badge>
        </p>
      </div>

      <div className="grid gap-2 sm:grid-cols-2">
        {BACKENDS.map((option) => (
          <button
            key={option.id}
            type="button"
            onClick={() => setBackend(option.id)}
            className={cn(
              "rounded-xl border p-3 text-left transition-colors",
              backend === option.id
                ? "border-primary bg-primary/10"
                : "border-border bg-surface hover:border-primary/40",
            )}
          >
            <p className="flex items-center gap-2 text-[13px] font-medium">
              <option.icon className="size-4 text-primary" />
              {option.title}
              {config.effective_backend === option.id ? <Badge tone="success">active</Badge> : null}
              {config.effective_backend !== option.id && backend === option.id ? (
                <Badge tone="muted">selected</Badge>
              ) : null}
            </p>
            <p className="mt-1 text-[11.5px] leading-relaxed text-muted-foreground">{option.desc}</p>
          </button>
        ))}
      </div>

      {backend === "superserve" ? (
        <div className="space-y-3 rounded-xl border border-border bg-surface p-3.5">
          <Field
            label="Superserve API key"
            hint={config.superserve_configured ? `Saved (${config.superserve_key_masked}) — leave empty to keep it.` : "From console.superserve.ai → Settings → API keys (ss_live_…). Stored encrypted."}
          >
            <Input
              type="password"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder={config.superserve_configured ? "••••••••" : "ss_live_…"}
              className="h-9 font-mono text-xs"
            />
          </Field>
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Template" hint="Ubuntu 24.04 base, or your own template name/UUID.">
              <Input
                value={template}
                onChange={(e) => setTemplate(e.target.value)}
                placeholder="superserve/base"
                className="h-9 font-mono text-xs"
              />
            </Field>
            <Field label="Warm pool size" hint="Standby cloud boxes (0–20). Unhealthy ones auto-replace.">
              <Input
                type="number"
                min={0}
                max={20}
                value={poolSize}
                onChange={(e) => setPoolSize(Number(e.target.value))}
                className="h-9 font-mono text-xs"
              />
            </Field>
          </div>
          <div className="rounded-lg bg-muted px-3 py-2 text-[11.5px] text-muted-foreground">
            Pool:{" "}
            {config.pool.active ? (
              <>
                <span className="font-medium text-foreground">{config.pool.warm ?? 0}/{config.pool.size ?? 0} warm</span>
                {config.pool.quota_exhausted ? (
                  <span className="text-danger"> · quota exhausted — backing off, chats fall back to local</span>
                ) : null}
                {config.pool.last_error && !config.pool.quota_exhausted ? (
                  <span> · last error: {config.pool.last_error}</span>
                ) : null}
              </>
            ) : (
              "starts on the first cloud chat"
            )}
          </div>
        </div>
      ) : null}

      {error ? <p className="text-[12.5px] text-danger animate-message-in">{error}</p> : null}

      <div className="flex items-center gap-2">
        <Button size="sm" disabled={busy} onClick={() => void save()}>
          {busy ? <Loader2 className="size-3.5 animate-spin" /> : <Save className="size-3.5" />}
          Save sandbox settings
        </Button>
        {saved ? <span className="text-[12.5px] text-emerald-500">Saved — new chats use it.</span> : null}
      </div>
    </div>
  );
}
