import { ConnectorsTab } from "@/components/settings/ConnectorsTab";

/** Social + messaging accounts (Telegram, Discord, X, Meta, WhatsApp…). */
export function SocialTab() {
  return (
    <div className="space-y-4">
      <div>
        <h3 className="text-sm font-semibold tracking-tight">Social accounts</h3>
        <p className="text-[12.5px] text-muted-foreground">
          Connect with <span className="font-medium text-foreground">OAuth</span> (your own app —
          tokens refresh automatically) or paste a{" "}
          <span className="font-medium text-foreground">token</span> directly. The agent can then
          read and post through the <code className="rounded bg-muted px-1 font-mono">social</code>{" "}
          tool — posting always asks first.
        </p>
      </div>
      <ConnectorsTab kind="social" />
    </div>
  );
}
