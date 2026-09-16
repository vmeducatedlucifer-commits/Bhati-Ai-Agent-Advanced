import { useEffect, useMemo, useRef, useState } from "react";
import { ExternalLink, KeyRound, Loader2, Plug, Server, ShieldCheck, Unplug } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/primitives";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { api } from "@/lib/api";
import type { ConnectorInfo } from "@/types";
import type { ManusConnectorCatalogItem } from "@/components/settings/manusConnectorCatalog";

const DIRECT_SERVICE_BY_NAME: Record<string, string> = {
  GitHub: "github",
  Slack: "slack",
  Notion: "notion",
  Linear: "linear",
  Stripe: "stripe",
  Vercel: "vercel",
  "Hugging Face": "huggingface",
};

export function ConnectorSetupDialog({ item, open, onOpenChange }: { item: ManusConnectorCatalogItem | null; open: boolean; onOpenChange: (open: boolean) => void }) {
  const [connector, setConnector] = useState<ConnectorInfo | null>(null);
  const [token, setToken] = useState("");
  const [extra, setExtra] = useState<Record<string, string>>({});
  const [mcpUrl, setMcpUrl] = useState("");
  const [mcpToken, setMcpToken] = useState("");
  const [clientId, setClientId] = useState("");
  const [clientSecret, setClientSecret] = useState("");
  const popupRef = useRef<Window | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const serviceKey = item ? DIRECT_SERVICE_BY_NAME[item.name] : undefined;

  useEffect(() => {
    if (!open || !item) return;
    setToken("");
    setExtra({});
    setMcpUrl("");
    setMcpToken("");
    setClientId("");
    setClientSecret("");
    setMessage("");
    setError("");
    if (serviceKey) void api.listConnectors().then((list) => setConnector(list.find((entry) => entry.service === serviceKey) ?? null)).catch(() => setConnector(null));
    else setConnector(null);
  }, [item, open, serviceKey]);

  useEffect(() => {
    const onMessage = (event: MessageEvent) => {
      const data = event.data as { type?: string; service?: string; ok?: boolean; error?: string };
      if (!data || data.type !== "bhati:oauth:done" || data.service !== serviceKey) return;
      popupRef.current?.close();
      popupRef.current = null;
      setBusy(false);
      if (data.ok) setMessage(`${item?.name ?? serviceKey} connected and verified.`);
      else setError(data.error || "Authorization failed");
    };
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, [item?.name, serviceKey]);

  const fields = useMemo(() => connector?.fields ?? [{ key: "token", label: "API token", secret: true }], [connector]);
  if (!item) return null;

  const connectToken = async () => {
    if (!serviceKey || !token.trim()) return;
    setBusy(true); setError(""); setMessage("");
    try {
      await api.connect(serviceKey, token.trim(), extra);
      setToken("");
      setMessage(`${item.name} connected and verified. You can now select it in agent tasks.`);
      const list = await api.listConnectors();
      setConnector(list.find((entry) => entry.service === serviceKey) ?? null);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Connection failed");
    } finally { setBusy(false); }
  };

  const disconnect = async () => {
    if (!serviceKey) return;
    setBusy(true); setError("");
    try { await api.disconnect(serviceKey); setConnector((current) => current ? { ...current, connected: false } : current); setMessage(`${item.name} disconnected.`); }
    catch (exc) { setError(exc instanceof Error ? exc.message : "Disconnect failed"); }
    finally { setBusy(false); }
  };

  const startOAuth = async () => {
    if (!serviceKey || !connector?.oauth || !clientId.trim()) return;
    setBusy(true); setError(""); setMessage("");
    try {
      const { url } = await api.oauthUrl(serviceKey, {
        client_id: clientId.trim(),
        client_secret: clientSecret,
        redirect_uri: api.oauthCallbackUrl(serviceKey),
        scopes: connector.oauth.scopes,
      });
      popupRef.current = window.open(url, `bhati-oauth-${serviceKey}`, "width=600,height=750");
      if (!popupRef.current) { setBusy(false); setError("Popup blocked — allow popups for this site and try again."); }
    } catch (exc) { setBusy(false); setError(exc instanceof Error ? exc.message : "OAuth setup failed"); }
  };

  const connectMcp = async () => {
    if (!mcpUrl.trim()) return;
    setBusy(true); setError(""); setMessage("");
    try {
      const safeName = item.name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 50) || "catalog-connector";
      await api.addMcp({ name: `manus-${safeName}`, transport: "http", url: mcpUrl.trim(), headers: mcpToken.trim() ? { Authorization: `Bearer ${mcpToken.trim()}` } : {} });
      setMessage(`${item.name} MCP server added. Its tools are being discovered in the background.`);
      setMcpToken("");
    } catch (exc) { setError(exc instanceof Error ? exc.message : "MCP setup failed"); }
    finally { setBusy(false); }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[86vh] w-[min(560px,94vw)] overflow-y-auto rounded-2xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2"><span className="flex size-8 items-center justify-center rounded-xl bg-primary/10 text-primary"><Plug className="size-4" /></span>{item.name}</DialogTitle>
          <DialogDescription>{item.description}. Choose a real connection method below; credentials are stored encrypted and verified before use.</DialogDescription>
        </DialogHeader>

        {connector ? (
          <section className="space-y-3 rounded-xl border border-border bg-muted/25 p-3">
            <div className="flex items-center justify-between gap-3"><div><p className="text-sm font-medium">Direct connector</p><p className="text-[11.5px] text-muted-foreground">{connector.help}</p></div><Badge tone={connector.connected ? "success" : "muted"}>{connector.connected ? "Connected" : connector.oauth ? "OAuth / token" : "Token"}</Badge></div>
            {connector.connected ? (
              <div className="flex items-center justify-between gap-2 rounded-lg bg-emerald-500/10 px-3 py-2 text-[12px] text-emerald-700 dark:text-emerald-300"><span>Account verified and ready for agent tasks.</span><Button variant="ghost" size="sm" onClick={() => void disconnect()} disabled={busy}><Unplug className="size-3.5" /> Disconnect</Button></div>
            ) : (
              <>
                {connector.oauth ? <div className="space-y-2 rounded-lg border border-primary/20 bg-primary/5 p-2.5"><p className="flex items-center gap-1.5 text-[11.5px] font-medium"><ShieldCheck className="size-3.5 text-primary" /> OAuth authorization</p><div className="flex flex-col gap-2 sm:flex-row"><Input value={clientId} placeholder="OAuth client ID" onChange={(event) => setClientId(event.target.value)} /><Input type="password" value={clientSecret} placeholder="Client secret (optional)" onChange={(event) => setClientSecret(event.target.value)} /><Button variant="outline" onClick={() => void startOAuth()} disabled={!clientId.trim() || busy}>{busy ? <Loader2 className="size-3.5 animate-spin" /> : <ShieldCheck className="size-3.5" />} Authorize</Button></div><p className="text-[10.5px] text-muted-foreground">Redirect URI: <code className="break-all">{api.oauthCallbackUrl(serviceKey ?? "")}</code></p></div> : null}
                {(fields.filter((field) => !field.secret)).map((field) => <Input key={field.key} value={extra[field.key] ?? ""} placeholder={field.label} onChange={(event) => setExtra((current) => ({ ...current, [field.key]: event.target.value }))} />)}
                <div className="flex gap-2"><Input type="password" value={token} placeholder={fields.find((field) => field.secret)?.label ?? "API token"} onChange={(event) => setToken(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter") void connectToken(); }} /><Button onClick={() => void connectToken()} disabled={!token.trim() || busy}>{busy ? <Loader2 className="size-3.5 animate-spin" /> : <KeyRound className="size-3.5" />} Connect</Button></div>
                <p className="flex items-center gap-1 text-[11px] text-muted-foreground"><ShieldCheck className="size-3" /> Token is probed against the provider before it is saved.</p>
              </>
            )}
            {connector.docs ? <a href={connector.docs} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-[11px] text-primary hover:underline">Provider token documentation <ExternalLink className="size-3" /></a> : null}
          </section>
        ) : (
          <section className="space-y-3 rounded-xl border border-amber-500/25 bg-amber-500/[.06] p-3">
            <div className="flex items-start gap-2"><Server className="mt-0.5 size-4 shrink-0 text-amber-600" /><div><p className="text-sm font-medium">Connect through MCP</p><p className="text-[11.5px] leading-relaxed text-muted-foreground">This catalog provider needs a provider-specific MCP server or OAuth app configuration. Add its hosted MCP endpoint here and Bhati will discover the available tools.</p></div></div>
            <Input value={mcpUrl} placeholder="https://your-mcp-server.example.com/mcp" onChange={(event) => setMcpUrl(event.target.value)} />
            <div className="flex gap-2"><Input type="password" value={mcpToken} placeholder="Optional bearer/API token" onChange={(event) => setMcpToken(event.target.value)} /><Button onClick={() => void connectMcp()} disabled={!mcpUrl.trim() || busy}>{busy ? <Loader2 className="size-3.5 animate-spin" /> : <Server className="size-3.5" />} Add MCP</Button></div>
            <p className="text-[11px] text-muted-foreground">Use the provider's official MCP endpoint or your own adapter. No credential is sent until you press Add MCP.</p>
          </section>
        )}
        {message ? <p className="rounded-lg bg-emerald-500/10 px-3 py-2 text-[12px] text-emerald-700 dark:text-emerald-300">{message}</p> : null}
        {error ? <p className="rounded-lg bg-danger/10 px-3 py-2 text-[12px] text-danger">{error}</p> : null}
      </DialogContent>
    </Dialog>
  );
}
