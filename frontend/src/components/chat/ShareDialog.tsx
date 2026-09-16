import { Copy, Eye, Link2, Mail, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { api } from "@/lib/api";

interface Share {
  id: string;
  thread_id: string;
  token: string;
  role: string;
  views: number;
  created_at: string;
}

export function ShareDialog({
  open,
  onOpenChange,
  threadId,
  threadTitle,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  threadId: string | null;
  threadTitle: string;
}) {
  const [shares, setShares] = useState<Share[]>([]);
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (open && threadId) {
      void api.listShares(threadId).then(setShares).catch(() => setShares([]));
      setSent(null);
    }
  }, [open, threadId]);

  if (!threadId) return null;
  const linkFor = (token: string) => `${window.location.origin}/s/${token}`;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[84vh] w-[min(520px,94vw)] overflow-y-auto scrollbar-thin">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Link2 className="size-4 text-primary" />
            Share “{threadTitle}”
          </DialogTitle>
        </DialogHeader>

        <div className="space-y-3">
          <Button
            disabled={busy}
            onClick={async () => {
              setBusy(true);
              try {
                await api.createShare(threadId);
                setShares(await api.listShares(threadId));
              } finally {
                setBusy(false);
              }
            }}
          >
            Create public read-only link
          </Button>

          {shares.map((s) => (
            <div key={s.id} className="rounded-xl border border-border bg-surface p-3">
              <div className="flex items-center gap-2">
                <code className="min-w-0 flex-1 truncate font-mono text-[11.5px] text-primary">
                  {linkFor(s.token)}
                </code>
                <Button
                  size="xs"
                  variant="outline"
                  onClick={() => void navigator.clipboard?.writeText(linkFor(s.token))}
                >
                  <Copy className="size-3.5" />
                  Copy
                </Button>
                <Button size="xs" variant="ghost" onClick={async () => {
                  await api.revokeShare(s.token);
                  setShares((prev) => prev.filter((x) => x.id !== s.id));
                }}>
                  <Trash2 className="size-3.5 text-danger" />
                </Button>
              </div>
              <p className="mt-1 flex items-center gap-1 text-[11px] text-muted-foreground">
                <Eye className="size-3" />
                {s.views} view{s.views === 1 ? "" : "s"} · read-only
              </p>
            </div>
          ))}

          <div className="rounded-xl border border-dashed border-border p-3">
            <p className="mb-2 flex items-center gap-1.5 text-[12.5px] font-medium">
              <Mail className="size-3.5 text-primary" />
              Email transcript
            </p>
            <div className="flex gap-2">
              <Input
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="you@example.com"
                className="h-8 text-xs"
              />
              <Button
                size="sm"
                disabled={!email.includes("@")}
                onClick={async () => {
                  await api.emailTranscript(threadId, email.trim());
                  setSent(email.trim());
                }}
              >
                Send
              </Button>
            </div>
            {sent ? <p className="mt-1.5 text-[12px] text-emerald-500">Sent to {sent}</p> : null}
            <p className="mt-1 text-[10.5px] text-muted-foreground">Requires SMTP_* configured on the backend.</p>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
