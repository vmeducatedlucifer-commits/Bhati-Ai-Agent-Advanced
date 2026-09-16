import { ScrollText } from "lucide-react";
import { useEffect, useState } from "react";
import { Badge } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { relativeTime } from "@/lib/utils";

interface Entry {
  id: number;
  actor: string;
  action: string;
  detail: Record<string, unknown>;
  created_at: string;
}

export function AuditTab() {
  const [entries, setEntries] = useState<Entry[]>([]);

  useEffect(() => {
    void api.listAudit(150).then(setEntries).catch(() => setEntries([]));
  }, []);

  return (
    <div className="space-y-3">
      <div>
        <h3 className="text-sm font-semibold tracking-tight">Audit trail</h3>
        <p className="text-[12.5px] text-muted-foreground">
          Who did what — logins, deletes, shares, pushes, restores. Newest first.
        </p>
      </div>
      {entries.length === 0 ? (
        <p className="py-4 text-center text-[12.5px] text-muted-foreground">No audited actions yet.</p>
      ) : (
        <ul className="space-y-1.5">
          {entries.map((e) => (
            <li key={e.id} className="flex items-start gap-2 rounded-lg border border-border bg-surface px-3 py-2">
              <ScrollText className="mt-0.5 size-3.5 shrink-0 text-muted-foreground" />
              <div className="min-w-0 flex-1">
                <p className="flex flex-wrap items-center gap-1.5 text-[12.5px]">
                  <Badge tone="muted">{e.action}</Badge>
                  <span className="text-muted-foreground">by {e.actor}</span>
                </p>
                {Object.keys(e.detail).length > 0 ? (
                  <p className="mt-0.5 truncate font-mono text-[11px] text-muted-foreground">
                    {JSON.stringify(e.detail)}
                  </p>
                ) : null}
              </div>
              <span className="shrink-0 text-[10.5px] text-muted-foreground">{relativeTime(e.created_at)}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
