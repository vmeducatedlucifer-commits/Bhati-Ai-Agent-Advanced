import { Check, Loader2, Plus, RefreshCw, Trash2, X } from "lucide-react";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Field, Input } from "@/components/ui/input";
import { Badge, Switch } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { useStore } from "@/lib/store";
import type { ProviderInfo } from "@/types";

interface Draft {
  name: string;
  kind: "openai" | "anthropic";
  base_url: string;
  api_key: string;
  default_model: string;
}

const EMPTY: Draft = { name: "", kind: "openai", base_url: "", api_key: "", default_model: "" };

export function ProvidersTab() {
  const [providers, setProviders] = useState<ProviderInfo[]>([]);
  const [presets, setPresets] = useState<{ name: string; kind: string; base_url: string; default_model: string }[]>([]);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [busy, setBusy] = useState(false);
  const [testResult, setTestResult] = useState<{ ok: boolean; message: string } | null>(null);
  const refreshModels = useStore((s) => s.refreshModels);

  const load = async () => setProviders(await api.listProviders());

  useEffect(() => {
    void load();
    void api.providerPresets().then(setPresets);
  }, []);

  const save = async () => {
    if (!draft) return;
    setBusy(true);
    try {
      await api.createProvider({ ...draft, models: draft.default_model ? [draft.default_model] : [] });
      setDraft(null);
      setTestResult(null);
      await load();
      await refreshModels();
    } finally {
      setBusy(false);
    }
  };

  const test = async () => {
    if (!draft) return;
    setBusy(true);
    setTestResult(null);
    try {
      const result = await api.testProvider({ ...draft, models: draft.default_model ? [draft.default_model] : [] });
      setTestResult({
        ok: result.ok,
        message: result.ok
          ? result.reply
            ? `Replied "${result.reply}"`
            : `Found ${result.models?.length ?? 0} models`
          : (result.error ?? "Failed"),
      });
      if (result.ok && result.models?.length && !draft.default_model) {
        setDraft({ ...draft, default_model: result.models[0] });
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-4">
      <div className="space-y-2">
        {providers.map((provider) => (
          <div
            key={provider.id}
            className="flex items-center gap-3 rounded-xl border border-border bg-surface px-3 py-2.5"
          >
            <div className="min-w-0 flex-1">
              <p className="flex items-center gap-2 text-[13px] font-medium">
                {provider.name}
                <Badge tone="muted">{provider.kind}</Badge>
                {provider.readonly ? <Badge tone="muted">env</Badge> : null}
              </p>
              <p className="truncate text-[11.5px] text-muted-foreground">
                {provider.base_url} · {provider.models.length} model
                {provider.models.length === 1 ? "" : "s"}
                {provider.has_key ? ` · key ${provider.api_key_masked}` : " · no key"}
              </p>
            </div>

            {!provider.readonly && (
              <>
                <Switch
                  checked={provider.enabled}
                  onCheckedChange={async (enabled) => {
                    await api.updateProvider(provider.id, { enabled });
                    await load();
                    await refreshModels();
                  }}
                />
                <Button
                  variant="ghost"
                  size="icon-sm"
                  title="Refresh model list"
                  onClick={async () => {
                    await api.refreshModels(provider.id);
                    await load();
                    await refreshModels();
                  }}
                >
                  <RefreshCw className="size-3.5" />
                </Button>
                <Button
                  variant="ghost"
                  size="icon-sm"
                  onClick={async () => {
                    if (!confirm(`Remove ${provider.name}?`)) return;
                    await api.deleteProvider(provider.id);
                    await load();
                    await refreshModels();
                  }}
                >
                  <Trash2 className="size-3.5 text-danger" />
                </Button>
              </>
            )}
          </div>
        ))}
      </div>

      {draft ? (
        <div className="space-y-3 rounded-xl border border-border bg-surface p-3.5">
          <div className="flex items-center justify-between">
            <p className="text-[13px] font-medium">New provider</p>
            <Button variant="ghost" size="icon-sm" onClick={() => setDraft(null)}>
              <X className="size-3.5" />
            </Button>
          </div>

          <div className="flex flex-wrap gap-1.5">
            {presets.map((preset) => (
              <button
                key={preset.name}
                type="button"
                onClick={() =>
                  setDraft({
                    name: preset.name,
                    kind: preset.kind as Draft["kind"],
                    base_url: preset.base_url,
                    api_key: draft.api_key,
                    default_model: preset.default_model,
                  })
                }
                className="rounded-full border border-border px-2.5 py-1 text-[11.5px] text-muted-foreground transition-colors hover:border-primary/40 hover:text-foreground"
              >
                {preset.name}
              </button>
            ))}
          </div>

          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Name">
              <Input value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} />
            </Field>
            <Field label="API style">
              <select
                value={draft.kind}
                onChange={(e) => setDraft({ ...draft, kind: e.target.value as Draft["kind"] })}
                className="h-9 w-full rounded-lg border border-input bg-surface px-3 text-sm"
              >
                <option value="openai">OpenAI-compatible</option>
                <option value="anthropic">Anthropic</option>
              </select>
            </Field>
          </div>

          <Field label="Base URL" hint="Include /v1 when the provider expects it.">
            <Input
              value={draft.base_url}
              placeholder="https://api.openai.com/v1"
              onChange={(e) => setDraft({ ...draft, base_url: e.target.value })}
            />
          </Field>

          <Field label="API key">
            <Input
              type="password"
              value={draft.api_key}
              placeholder="sk-…"
              onChange={(e) => setDraft({ ...draft, api_key: e.target.value })}
            />
          </Field>

          <Field label="Default model">
            <Input
              value={draft.default_model}
              placeholder="gpt-4o"
              onChange={(e) => setDraft({ ...draft, default_model: e.target.value })}
            />
          </Field>

          {testResult ? (
            <p
              className={`flex items-center gap-1.5 text-[12.5px] ${testResult.ok ? "text-emerald-500" : "text-danger"}`}
            >
              {testResult.ok ? <Check className="size-3.5" /> : <X className="size-3.5" />}
              {testResult.message}
            </p>
          ) : null}

          <div className="flex gap-2">
            <Button size="sm" variant="outline" disabled={busy || !draft.base_url} onClick={() => void test()}>
              {busy ? <Loader2 className="size-3.5 animate-spin" /> : null}
              Test
            </Button>
            <Button size="sm" disabled={busy || !draft.name || !draft.base_url} onClick={() => void save()}>
              Save provider
            </Button>
          </div>
        </div>
      ) : (
        <Button variant="outline" size="sm" onClick={() => setDraft({ ...EMPTY })}>
          <Plus className="size-4" />
          Add provider
        </Button>
      )}
    </div>
  );
}
