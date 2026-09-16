import { AlertTriangle, ChartColumn, Coins, Gauge, Trophy } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { api, displayModelName } from "@/lib/api";

/** Rough USD per 1M tokens [input, output]. Unknown models → 0. */
const PRICING: Record<string, [number, number]> = {
  "gpt-4o": [2.5, 10],
  "gpt-4o-mini": [0.15, 0.6],
  "gpt-4.1": [2, 8],
  "gpt-4.1-mini": [0.4, 1.6],
  "o1": [15, 60],
  "o3-mini": [1.1, 4.4],
  "claude-3-5-sonnet": [3, 15],
  "claude-3-7-sonnet": [3, 15],
  "claude-3-5-haiku": [0.8, 4],
  "deepseek-chat": [0.27, 1.1],
  "deepseek-reasoner": [0.55, 2.19],
};

function priceFor(model: string): [number, number] {
  const key = model.toLowerCase();
  for (const [name, price] of Object.entries(PRICING)) {
    if (key.includes(name)) return price;
  }
  return [0, 0];
}

export function costOf(model: string, prompt: number, completion: number): number {
  const [pin, pout] = priceFor(model);
  return (prompt / 1e6) * pin + (completion / 1e6) * pout;
}

interface Overview {
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  runs: number;
  threads: number;
  projects: number;
}

interface ByModel {
  model: string;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  runs: number;
  avg_latency_ms: number;
}

interface DayStat {
  day: string;
  prompt_tokens: number;
  completion_tokens: number;
  runs: number;
}

const BUDGET_KEY = "bhati.budgetUsd";

export function InsightsTab() {
  const [overview, setOverview] = useState<Overview | null>(null);
  const [byModel, setByModel] = useState<ByModel[]>([]);
  const [daily, setDaily] = useState<DayStat[]>([]);
  const [budget, setBudget] = useState(() => localStorage.getItem(BUDGET_KEY) ?? "");
  const [budgetInput, setBudgetInput] = useState(budget);

  useEffect(() => {
    void api.statsOverview().then(setOverview).catch(() => {});
    void api.statsByModel().then(setByModel).catch(() => {});
    void api.statsDaily(14).then(setDaily).catch(() => {});
  }, []);

  const totalCost = useMemo(
    () => byModel.reduce((sum, m) => sum + costOf(m.model, m.prompt_tokens, m.completion_tokens), 0),
    [byModel],
  );
  const budgetNum = Number(budget) || 0;
  const maxDay = Math.max(1, ...daily.map((d) => d.prompt_tokens + d.completion_tokens));
  const leaderboard = useMemo(
    () => [...byModel].sort((a, b) => a.avg_latency_ms - b.avg_latency_ms),
    [byModel],
  );

  const saveBudget = () => {
    try {
      if (budgetInput.trim()) localStorage.setItem(BUDGET_KEY, budgetInput.trim());
      else localStorage.removeItem(BUDGET_KEY);
    } catch {
      /* ignore */
    }
    setBudget(budgetInput.trim());
  };

  return (
    <div className="space-y-5">
      {/* overview cards */}
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        <div className="rounded-xl border border-border bg-surface p-3">
          <p className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
            <ChartColumn className="size-3.5 text-primary" />
            Tokens
          </p>
          <p className="mt-1 truncate text-lg font-semibold tabular-nums">
            {overview ? overview.total_tokens.toLocaleString() : "…"}
          </p>
        </div>
        <div className="rounded-xl border border-border bg-surface p-3">
          <p className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
            <Coins className="size-3.5 text-primary" />
            Est. cost
          </p>
          <p className="mt-1 truncate text-lg font-semibold tabular-nums">${totalCost.toFixed(4)}</p>
        </div>
        <div className="rounded-xl border border-border bg-surface p-3">
          <p className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
            <Gauge className="size-3.5 text-primary" />
            Agent runs
          </p>
          <p className="mt-1 truncate text-lg font-semibold tabular-nums">
            {overview ? String(overview.runs) : "…"}
          </p>
        </div>
        <div className="rounded-xl border border-border bg-surface p-3">
          <p className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
            <Trophy className="size-3.5 text-primary" />
            Threads
          </p>
          <p className="mt-1 truncate text-lg font-semibold tabular-nums">
            {overview ? String(overview.threads) : "…"}
          </p>
        </div>
      </div>

      {/* budget */}
      <div className="rounded-xl border border-border bg-surface p-4">
        <p className="mb-1 text-xs font-medium">Monthly budget alert (USD)</p>
        <div className="flex gap-2">
          <Input value={budgetInput} onChange={(e) => setBudgetInput(e.target.value)} placeholder="e.g. 10" className="h-8 text-xs" inputMode="decimal" />
          <Button size="sm" variant="outline" onClick={saveBudget}>Save</Button>
        </div>
        {budgetNum > 0 && (
          <div className="mt-2">
            <div className="h-1.5 overflow-hidden rounded-full bg-muted">
              <div
                className={`h-full rounded-full transition-all ${totalCost > budgetNum ? "bg-danger" : "bg-emerald-500"}`}
                style={{ width: `${Math.min(100, (totalCost / budgetNum) * 100)}%` }}
              />
            </div>
            <p className={`mt-1 flex items-center gap-1 text-[11px] ${totalCost > budgetNum ? "text-danger" : "text-muted-foreground"}`}>
              {totalCost > budgetNum ? <AlertTriangle className="size-3" /> : null}
              ${totalCost.toFixed(4)} of ${budgetNum.toFixed(2)} used
            </p>
          </div>
        )}
      </div>

      {/* daily chart */}
      <div className="rounded-xl border border-border bg-surface p-4">
        <p className="mb-3 text-xs font-medium">Tokens per day (14d)</p>
        {daily.length ? (
          <div className="flex h-28 items-end gap-1">
            {daily.map((d) => {
              const total = d.prompt_tokens + d.completion_tokens;
              const h = Math.max(4, (total / maxDay) * 100);
              return (
                <div key={d.day} className="group relative flex-1" title={`${d.day}: ${total.toLocaleString()} tokens, ${d.runs} runs`}>
                  <div className="w-full rounded-t bg-primary/70 transition-all group-hover:bg-primary" style={{ height: `${h}%`, minHeight: 4 }} />
                  <p className="mt-1 truncate text-center text-[9px] text-muted-foreground">{d.day.slice(5)}</p>
                </div>
              );
            })}
          </div>
        ) : (
          <p className="text-[12px] text-muted-foreground">No usage yet — run the agent first.</p>
        )}
      </div>

      {/* leaderboard */}
      <div className="rounded-xl border border-border bg-surface p-4">
        <p className="mb-2 flex items-center gap-1.5 text-xs font-medium">
          <Trophy className="size-3.5 text-primary" />
          Model leaderboard — fastest first
        </p>
        {leaderboard.length ? (
          <ul className="space-y-1.5">
            {leaderboard.map((m, i) => (
              <li key={m.model} className="flex items-center gap-2 rounded-lg border border-border px-3 py-2">
                <span className="w-5 text-center font-mono text-[12px] text-muted-foreground">{i + 1}</span>
                <div className="min-w-0 flex-1">
                  <p className="truncate font-mono text-[12px]">{displayModelName(m.model)}</p>
                  <p className="text-[10.5px] tabular-nums text-muted-foreground">
                    {m.total_tokens.toLocaleString()} tok · {m.runs} runs · avg {(m.avg_latency_ms / 1000).toFixed(1)}s · ≈${costOf(m.model, m.prompt_tokens, m.completion_tokens).toFixed(4)}
                  </p>
                </div>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-[12px] text-muted-foreground">No model data yet.</p>
        )}
      </div>
    </div>
  );
}
