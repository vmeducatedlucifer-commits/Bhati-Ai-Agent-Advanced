import { Bot, Check, KeyRound, Loader2, RefreshCw, Send, ShieldAlert, Users } from "lucide-react";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/primitives";
import { api } from "@/lib/api";

export function TelegramTab() {
  const [token, setToken] = useState("");
  const [allowedIds, setAllowedIds] = useState("");
  const [status, setStatus] = useState<{
    enabled: boolean;
    bot_username: string;
    token_masked: string;
    allowed_user_ids: string;
  } | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState<{ type: "success" | "error"; text: string } | null>(null);

  const fetchStatus = async () => {
    try {
      setLoading(true);
      const res = await api.getTelegramStatus();
      setStatus(res);
      setAllowedIds(res.allowed_user_ids || "");
    } catch (e: any) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void fetchStatus();
  }, []);

  const handleSave = async () => {
    if (!token && !status?.token_masked) {
      setMsg({ type: "error", text: "Please enter a valid Telegram Bot Token." });
      return;
    }
    setSaving(true);
    setMsg(null);
    try {
      const res = await api.updateTelegramConfig({
        bot_token: token || status?.token_masked || "",
        allowed_user_ids: allowedIds,
      });
      if (res.enabled) {
        setMsg({
          type: "success",
          text: `Bot @${res.bot_username || "your_bot"} successfully connected & live!`,
        });
      } else {
        setMsg({
          type: "error",
          text: "Bot token could not be verified by Telegram API. Check your token.",
        });
      }
      await fetchStatus();
    } catch (e: any) {
      setMsg({ type: "error", text: e.message || "Failed to update Telegram config." });
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-5">
      <div>
        <h3 className="text-sm font-semibold tracking-tight">Telegram Bot Remote Control</h3>
        <p className="text-[12.5px] text-muted-foreground">
          Interact with Rawal AI from Telegram. Execute code, run autonomous loops, and get live status updates.
        </p>
      </div>

      {/* Connection Status Card */}
      <div className="flex items-center justify-between rounded-xl border border-border bg-surface p-4">
        <div className="flex items-center gap-3">
          <div className="flex size-10 items-center justify-center rounded-xl bg-primary/10 text-primary">
            <Bot className="size-5" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <span className="text-sm font-medium">Telegram Bot</span>
              <Badge tone={status?.enabled ? "success" : "muted"}>
                {status?.enabled ? "Online" : "Offline / Unconfigured"}
              </Badge>
            </div>
            <p className="text-xs text-muted-foreground">
              {status?.bot_username ? `@${status.bot_username}` : "No bot currently connected"}
            </p>
          </div>
        </div>

        <Button variant="ghost" size="icon-sm" onClick={fetchStatus} disabled={loading}>
          <RefreshCw className={`size-3.5 ${loading ? "animate-spin" : ""}`} />
        </Button>
      </div>

      {msg && (
        <div
          className={`flex items-center gap-2 rounded-lg p-3 text-xs ${
            msg.type === "success"
              ? "border border-emerald-500/30 bg-emerald-500/10 text-emerald-400"
              : "border border-danger/30 bg-danger/10 text-danger"
          }`}
        >
          {msg.type === "success" ? <Check className="size-4 shrink-0" /> : <ShieldAlert className="size-4 shrink-0" />}
          <span>{msg.text}</span>
        </div>
      )}

      {/* Form Fields */}
      <div className="space-y-4 rounded-xl border border-border bg-surface p-4">
        <div className="space-y-1.5">
          <label className="flex items-center gap-2 text-xs font-medium">
            <KeyRound className="size-3.5 text-primary" />
            Telegram Bot Token
          </label>
          <Input
            type="password"
            value={token}
            onChange={(e) => setToken(e.target.value)}
            placeholder={status?.token_masked ? `Configured (${status.token_masked})` : "e.g. 123456789:ABCDefghIJKLmnop"}
            className="h-9 font-mono text-xs"
          />
          <p className="text-[11px] text-muted-foreground">
            Get your token from <a href="https://t.me/BotFather" target="_blank" rel="noreferrer" className="text-primary hover:underline">@BotFather</a> on Telegram.
          </p>
        </div>

        <div className="space-y-1.5">
          <label className="flex items-center gap-2 text-xs font-medium">
            <Users className="size-3.5 text-primary" />
            Allowed User IDs (Security White-list)
          </label>
          <Input
            value={allowedIds}
            onChange={(e) => setAllowedIds(e.target.value)}
            placeholder="e.g. 123456789, 987654321 (or * for all users)"
            className="h-9 font-mono text-xs"
          />
          <p className="text-[11px] text-muted-foreground">
            Comma-separated Telegram User IDs. Anyone not in this list will be rejected immediately. Find your ID using <a href="https://t.me/userinfobot" target="_blank" rel="noreferrer" className="text-primary hover:underline">@userinfobot</a>.
          </p>
        </div>

        <Button onClick={handleSave} disabled={saving} className="gap-2">
          {saving ? <Loader2 className="size-3.5 animate-spin" /> : <Send className="size-3.5" />}
          Save & Activate Bot
        </Button>
      </div>
    </div>
  );
}
