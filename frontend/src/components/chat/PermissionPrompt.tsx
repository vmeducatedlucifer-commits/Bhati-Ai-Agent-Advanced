import { ShieldAlert } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useStore } from "@/lib/store";

export function PermissionPrompt() {
  const permission = useStore((s) => s.permission);
  const answer = useStore((s) => s.answerPermission);
  if (!permission) return null;

  const preview =
    (permission.arguments?.command as string) ??
    (permission.arguments?.path as string) ??
    JSON.stringify(permission.arguments ?? {}).slice(0, 300);

  return (
    <div className="animate-fade-in rounded-xl border border-amber-500/40 bg-amber-500/5 p-3.5">
      <div className="flex items-start gap-2.5">
        <ShieldAlert className="mt-0.5 size-4 shrink-0 text-amber-500" />
        <div className="min-w-0 flex-1 space-y-2.5">
          <div>
            <p className="text-[13px] font-medium">
              Allow <span className="font-mono">{permission.tool}</span>?
            </p>
            <p className="text-xs text-muted-foreground">{permission.reason}</p>
          </div>
          <pre className="scrollbar-thin max-h-32 overflow-auto rounded-lg bg-background/60 p-2 font-mono text-[12px]">
            {preview}
          </pre>
          <div className="flex flex-wrap gap-2">
            <Button size="sm" onClick={() => void answer("allow")}>
              Allow once
            </Button>
            <Button size="sm" variant="outline" onClick={() => void answer("allow_always")}>
              Always allow {permission.tool}
            </Button>
            <Button size="sm" variant="ghost" onClick={() => void answer("deny")}>
              Deny
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
