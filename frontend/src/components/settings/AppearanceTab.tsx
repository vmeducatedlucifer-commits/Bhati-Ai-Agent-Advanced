import { Keyboard, Palette, RotateCcw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useStore } from "@/lib/store";

export function AppearanceTab() {
  const accentHue = useStore((s) => s.accentHue);
  const setAccentHue = useStore((s) => s.setAccentHue);
  const keymap = useStore((s) => s.keymap);
  const setKeymap = useStore((s) => s.setKeymap);

  return (
    <div className="space-y-5">
      <div className="rounded-xl border border-border bg-surface p-4">
        <p className="mb-1 flex items-center gap-2 text-xs font-medium">
          <Palette className="size-3.5 text-primary" />
          Theme builder — accent color
        </p>
        <p className="mb-3 text-[11px] text-muted-foreground">
          Slide to re-tint the whole UI instantly. Applies to light and dark mode.
        </p>
        <div className="flex items-center gap-3">
          <input
            type="range"
            min={0}
            max={360}
            value={accentHue ?? 14}
            onChange={(e) => setAccentHue(Number(e.target.value))}
            className="h-2 flex-1 cursor-pointer appearance-none rounded-full"
            style={{
              background: "linear-gradient(90deg,#ef4444,#f59e0b,#22c55e,#3b82f6,#a855f7,#ef4444)",
            }}
          />
          <span
            className="size-8 shrink-0 rounded-full border border-border shadow-inner"
            style={{ background: `hsl(${accentHue ?? 14} 63% 59%)` }}
          />
          {accentHue !== null ? (
            <Button size="xs" variant="ghost" onClick={() => setAccentHue(null)}>
              <RotateCcw className="size-3.5" />
              Reset
            </Button>
          ) : null}
        </div>
        <div className="mt-3 flex gap-2">
          {[14, 210, 150, 280, 0].map((h) => (
            <button
              key={h}
              type="button"
              title={`Hue ${h}`}
              onClick={() => setAccentHue(h)}
              className="size-7 rounded-full border-2 border-border transition-transform hover:scale-110"
              style={{
                background: `hsl(${h} 63% 59%)`,
                borderColor: accentHue === h ? "hsl(var(--foreground))" : undefined,
              }}
            />
          ))}
        </div>
      </div>

      <div className="rounded-xl border border-border bg-surface p-4">
        <p className="mb-1 flex items-center gap-2 text-xs font-medium">
          <Keyboard className="size-3.5 text-primary" />
          Keyboard shortcuts
        </p>
        <p className="mb-3 text-[11px] text-muted-foreground">
          Single keys combined with Ctrl/Cmd. Letters only, changes apply immediately.
        </p>
        <div className="space-y-2">
          {(
            [
              ["newChat", "New chat"],
              ["sidebar", "Toggle sidebar"],
              ["settings", "Open settings"],
            ] as const
          ).map(([key, label]) => (
            <div key={key} className="flex items-center gap-2">
              <p className="flex-1 text-[12.5px]">{label}</p>
              <kbd className="rounded bg-muted px-1.5 py-0.5 font-mono text-[11px]">Ctrl</kbd>
              <span className="text-muted-foreground">+</span>
              <Input
                value={keymap[key]}
                maxLength={1}
                onChange={(e) => {
                  const v = e.target.value.toLowerCase().replace(/[^a-z]/g, "");
                  if (v) setKeymap({ [key]: v });
                }}
                className="h-8 w-12 text-center font-mono text-xs"
              />
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
