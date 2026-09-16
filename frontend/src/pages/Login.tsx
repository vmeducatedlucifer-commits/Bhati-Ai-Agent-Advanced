import { Sparkles } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Field, Input } from "@/components/ui/input";
import { api, setToken } from "@/lib/api";

export function Login({ onSignedIn }: { onSignedIn: () => void }) {
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    setBusy(true);
    setError("");
    try {
      const result = await api.login(password);
      setToken(result.token);
      onSignedIn();
    } catch {
      setError("Wrong password");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="relative flex h-full items-center justify-center overflow-hidden bg-background p-6">
      {/* ambient orbs */}
      <span className="orb left-[18%] top-[14%] size-64 bg-primary/15 animate-orb-drift" />
      <span className="orb bottom-[12%] right-[16%] size-72 bg-orange-400/10 animate-orb-drift [animation-delay:2.5s]" />

      <div className="relative w-full max-w-sm space-y-5">
        <div className="rise-stagger stagger-1 flex flex-col items-center gap-2 text-center">
          <span className="flex size-14 items-center justify-center rounded-3xl bg-primary text-primary-foreground glow-soft animate-float">
            <Sparkles className="size-6" />
          </span>
          <h1 className="text-xl font-semibold tracking-tight">
            <span className="text-gradient">Rawal AI</span>
          </h1>
          <p className="text-[13px] text-muted-foreground">Sign in to reach your workspace.</p>
        </div>

        <div className="rise-stagger stagger-2 glass space-y-3 rounded-2xl p-5 shadow-xl">
          <Field label="Password">
            <Input
              autoFocus
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && void submit()}
            />
          </Field>
          {error ? <p className="animate-message-in text-[12.5px] text-danger">{error}</p> : null}
          <Button className="w-full glow-soft" disabled={!password || busy} onClick={() => void submit()}>
            {busy ? "Signing in…" : "Sign in"}
          </Button>
        </div>
      </div>
    </div>
  );
}
