import { CheckCircle2, ExternalLink, KeyRound, Loader2, Plug, ShieldCheck, Unplug } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import type { ConnectorInfo } from "@/types";

function accountSummary(account: Record<string, unknown>): string {
  return (
    Object.entries(account)
      .filter(([k, v]) => !k.startsWith("_") && typeof v === "string" && v)
      .map(([k, v]) => `${k}: ${v}`)
      .join(" · ")
  );
}

function OAuthBlock({ connector, onDone }: { connector: ConnectorInfo; onDone: () => void }) {
  const [clientId, setClientId] = useState("");
  const [clientSecret, setClientSecret] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const popupRef = useRef<Window | null>(null);
  const redirectUri = api.oauthCallbackUrl(connector.service);

  useEffect(() => {
    const onMessage = (event: MessageEvent) => {
      const data = event.data as { type?: string; service?: string; ok?: boolean; error?: string };
      if (!data || data.type !== "bhati:oauth:done" || data.service !== connector.service) return;
      popupRef.current?.close();
      popupRef.current = null;
      setBusy(false);
      if (data.ok) {
        setError("");
        setClientId("");
        setClientSecret("");
        onDone();
      } else {
        setError(data.error || "Authorization failed");
      }
    };
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, [connector.service, onDone]);

  const start = async () => {
    setBusy(true);
    setError("");
    try {
      const { url } = await api.oauthUrl(connector.service, {
        client_id: clientId.trim(),
        client_secret: clientSecret,
        redirect_uri: redirectUri,
        scopes: connector.oauth?.scopes ?? [],
      });
      popupRef.current = window.open(url, `bhati-oauth-${connector.service}`, "width=600,height=750");
      if (!popupRef.current) {
        setBusy(false);
        setError("Popup blocked — allow popups for this site and try again.");
      }
    } catch (exc) {
      setBusy(false);
      setError(exc instanceof Error ? exc.message : "Failed to start");
    }
  };

  return (
    <div className="mt-3 space-y-2 rounded-lg border border-primary/25 bg-primary/5 p-3">
      <p className="flex items-center gap-1.5 text-[12px] font-medium">
        <ShieldCheck className="size-3.5 text-primary" />
        Connect with {connector.label} (OAuth)
      </p>
      <p className="text-[11.5px] leading-relaxed text-muted-foreground">
        Register your own app{" "}
        {connector.oauth?.docs ? (
          <a href={connector.oauth.docs} target="_blank" rel="noreferrer" className="text-primary hover:underline">
            here
          </a>
        ) : null}{" "}
        and whitelist this redirect URI:
      </p>
      <code className="block break-all rounded bg-muted px-2 py-1 font-mono text-[10.5px]">{redirectUri}</code>
      <Input
        value={clientId}
        placeholder="Client ID (App ID / Key)"
        onChange={(e) => setClientId(e.target.value)}
        className="h-8 font-mono text-xs"
      />
      <div className="flex gap-2">
        <Input
          type="password"
          value={clientSecret}
          placeholder="Client secret"
          onChange={(e) => setClientSecret(e.target.value)}
          className="h-8 flex-1 font-mono text-xs"
        />
        <Button size="sm" disabled={!clientId.trim() || busy} onClick={() => void start()}>
          {busy ? <Loader2 className="size-3.5 animate-spin" /> : null}
          {busy ? "Waiting…" : "Authorize"}
        </Button>
      </div>
      <p className="text-[11px] text-muted-foreground">
        Scopes: <span className="font-mono">{(connector.oauth?.scopes ?? []).join(" ") || "—"}</span>
      </p>
      {error ? <p className="text-[12px] text-danger">{error}</p> : null}
    </div>
  );
}

export function ConnectorsTab({ kind = "general" }: { kind?: string }) {
  const [connectors, setConnectors] = useState<ConnectorInfo[]>([]);
  const [editing, setEditing] = useState<string | null>(null);
  const [oauthFor, setOauthFor] = useState<string | null>(null);
  const [token, setToken] = useState("");
  const [extra, setExtra] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [probed, setProbed] = useState<Record<string, string>>({});

  const load = async () => setConnectors(await api.listConnectors().catch(() => []));

  useEffect(() => {
    void load();
  }, []);

  const visible = connectors.filter((c) => (c.kind || "general") === kind);

  const openEditor = (service: string) => {
    setEditing(editing === service ? null : service);
    setOauthFor(null);
    setToken("");
    setExtra({});
    setError("");
  };

  const connect = async (service: string) => {
    setBusy(true);
    setError("");
    try {
      await api.connect(service, token, extra);
      setEditing(null);
      setToken("");
      setExtra({});
      await load();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Failed");
    } finally {
      setBusy(false);
    }
  };

  const probe = async (service: string) => {
    setProbed((prev) => ({ ...prev, [service]: "…" }));
    try {
      const result = await api.probeConnector(service);
      setProbed((prev) => ({
        ...prev,
        [service]: result.ok ? "verified just now" : `error: ${result.error ?? "failed"}`,
      }));
      await load();
    } catch (exc) {
      setProbed((prev) => ({ ...prev, [service]: exc instanceof Error ? exc.message : "failed" }));
    }
  };

  return (
    <div className="space-y-2">
      {visible.map((connector) => (
        <div key={connector.service} className="rounded-xl border border-border bg-surface p-3">
          <div className="flex items-center gap-3">
            <div className="min-w-0 flex-1">
              <p className="flex items-center gap-2 text-[13px] font-medium">
                {connector.label}
                {connector.connected ? <Badge tone="success">connected</Badge> : null}
                {connector.oauth ? <Badge tone="primary">OAuth</Badge> : null}
              </p>
              <p className="truncate text-[11.5px] text-muted-foreground">
                {connector.connected
                  ? accountSummary(connector.account) || probed[connector.service] || connector.token_masked
                  : connector.help}
              </p>
              {probed[connector.service] ? (
                <p className="mt-0.5 flex items-center gap-1 text-[11px] text-muted-foreground">
                  <CheckCircle2 className="size-3 text-emerald-500" />
                  {probed[connector.service]}
                </p>
              ) : null}
            </div>

            <a
              href={connector.docs}
              target="_blank"
              rel="noreferrer"
              className="shrink-0 text-muted-foreground hover:text-foreground"
              title="Where to get a token"
            >
              <ExternalLink className="size-3.5" />
            </a>

            {connector.connected ? (
              <>
                <Button variant="ghost" size="sm" onClick={() => void probe(connector.service)}>
                  Re-verify
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={async () => {
                    await api.disconnect(connector.service);
                    await load();
                  }}
                >
                  <Unplug className="size-3.5" />
                  Disconnect
                </Button>
              </>
            ) : (
              <>
                {connector.oauth ? (
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => {
                      setOauthFor(oauthFor === connector.service ? null : connector.service);
                      setEditing(null);
                      setError("");
                    }}
                  >
                    <ShieldCheck className="size-3.5" />
                    OAuth
                  </Button>
                ) : null}
                <Button variant="outline" size="sm" onClick={() => openEditor(connector.service)}>
                  {connector.oauth ? <KeyRound className="size-3.5" /> : <Plug className="size-3.5" />}
                  {connector.oauth ? "Token" : "Connect"}
                </Button>
              </>
            )}
          </div>

          {oauthFor === connector.service && !connector.connected ? (
            <OAuthBlock connector={connector} onDone={() => {
              setOauthFor(null);
              void load();
            }} />
          ) : null}

          {editing === connector.service && (
            <div className="mt-3 space-y-2">
              {(connector.fields ?? [{ key: "token", label: "API Token", secret: true }])
                .filter((f) => !f.secret)
                .map((field) => (
                  <Input
                    key={field.key}
                    value={extra[field.key] ?? ""}
                    placeholder={field.label}
                    onChange={(e) => setExtra((prev) => ({ ...prev, [field.key]: e.target.value }))}
                  />
                ))}
              <div className="flex gap-2">
                <Input
                  type="password"
                  autoFocus
                  value={token}
                  placeholder={(connector.fields ?? []).find((f) => f.secret)?.label ?? connector.help}
                  onChange={(e) => setToken(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && token && void connect(connector.service)}
                />
                <Button size="sm" disabled={!token || busy} onClick={() => void connect(connector.service)}>
                  {busy ? <Loader2 className="size-3.5 animate-spin" /> : null}
                  Save
                </Button>
              </div>
            </div>
          )}
          {(editing === connector.service || oauthFor === connector.service) && error ? (
            <p className="mt-2 text-[12.5px] text-danger">{error}</p>
          ) : null}
        </div>
      ))}
      {visible.length === 0 ? (
        <p className="py-6 text-center text-[12.5px] text-muted-foreground">
          No connectors in this group yet.
        </p>
      ) : null}
    </div>
  );
}
