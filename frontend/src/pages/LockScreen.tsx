import { Delete, Lock } from "lucide-react";
import { useState } from "react";
import { useStore } from "@/lib/store";
import { cn } from "@/lib/utils";

export function LockScreen() {
  const unlock = useStore((s) => s.unlock);
  const [pin, setPin] = useState("");
  const [error, setError] = useState(false);

  const press = (digit: string) => {
    setError(false);
    const next = (pin + digit).slice(0, 6);
    setPin(next);
    if (next.length >= 4) {
      void unlock(next).then((ok) => {
        if (!ok) {
          setError(true);
          setPin("");
        }
      });
    }
  };

  return (
    <div className="relative flex h-full flex-col items-center justify-center gap-6 overflow-hidden bg-background">
      <span className="orb left-[20%] top-[18%] size-64 bg-primary/15 animate-orb-drift" />
      <span className="rise-stagger stagger-1 relative flex size-14 items-center justify-center rounded-3xl bg-primary/15 text-primary">
        <Lock className="size-6" />
      </span>
      <div className="rise-stagger stagger-2 relative flex gap-2.5">
        {[0, 1, 2, 3, 4, 5].map((i) => (
          <span
            key={i}
            className={cn(
              "size-3.5 rounded-full border transition-all",
              i < pin.length ? "border-primary bg-primary scale-110" : "border-border",
              error && "animate-shake border-danger",
            )}
          />
        ))}
      </div>
      {error ? <p className="text-[12.5px] text-danger animate-message-in">Wrong PIN — try again</p> : null}
      <div className="rise-stagger stagger-3 relative grid grid-cols-3 gap-2.5">
        {["1", "2", "3", "4", "5", "6", "7", "8", "9", "", "0", "⌫"].map((key, i) => (
          <button
            key={i}
            type="button"
            disabled={!key}
            onClick={() => (key === "⌫" ? setPin((p) => p.slice(0, -1)) : press(key))}
            className="flex size-16 items-center justify-center rounded-full border border-border bg-surface text-xl font-medium transition-all hover:border-primary/50 hover:bg-accent active:scale-95 disabled:opacity-0"
          >
            {key === "⌫" ? <Delete className="size-5" /> : key}
          </button>
        ))}
      </div>
    </div>
  );
}
