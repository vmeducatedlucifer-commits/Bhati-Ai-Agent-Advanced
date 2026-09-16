import { CalendarClock, Play, Plus, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { activeProject, useStore } from "@/lib/store";
import { relativeTime } from "@/lib/utils";
import type { ScheduledJob } from "@/types";

const INTERVALS = [
  [15, "Every 15 min"],
  [60, "Hourly"],
  [360, "Every 6 hours"],
  [720, "Every 12 hours"],
  [1440, "Daily"],
  [10080, "Weekly"],
];

export function JobsTab() {
  const project = useStore(activeProject);
  const [jobs, setJobs] = useState<ScheduledJob[]>([]);
  const [name, setName] = useState("");
  const [prompt, setPrompt] = useState("");
  const [interval, setInterval] = useState(60);
  const [formOpen, setFormOpen] = useState(false);

  const load = async () => {
    if (!project) return;
    setJobs(await api.listJobs(project.id).catch(() => []));
  };

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [project?.id]);

  if (!project) return <p className="text-[13px] text-muted-foreground">Create a project first.</p>;

  return (
    <div className="space-y-4">
      <div>
        <h3 className="text-sm font-semibold tracking-tight">Scheduled agent runs</h3>
        <p className="text-[12.5px] text-muted-foreground">
          Cron-style prompts that run on their own in this project — reports, health checks, dependency
          sweeps. A new thread is created per job; runs while the backend is up.
        </p>
      </div>

      <ul className="space-y-2">
        {jobs.map((job) => (
          <li key={job.id} className="rounded-xl border border-border bg-surface p-3">
            <div className="flex items-center gap-2">
              <CalendarClock className="size-4 shrink-0 text-primary" />
              <p className="min-w-0 flex-1 truncate text-[13px] font-medium">{job.name}</p>
              <Badge tone={job.enabled ? "success" : "muted"}>{job.enabled ? "on" : "off"}</Badge>
              <Badge tone={job.last_status === "ok" ? "success" : job.last_status === "error" ? "danger" : "muted"}>
                {job.last_status}
              </Badge>
            </div>
            <p className="mt-1 line-clamp-2 text-[12px] text-muted-foreground">{job.prompt}</p>
            <p className="mt-1 text-[11px] text-muted-foreground">
              Every {job.interval_minutes >= 60 ? `${job.interval_minutes / 60}h` : `${job.interval_minutes}m`}
              {job.next_run_at ? ` · next ${relativeTime(job.next_run_at)}` : ""}
              {job.last_run_at ? ` · last ${relativeTime(job.last_run_at)}` : ""}
            </p>
            <div className="mt-2 flex gap-1.5">
              <Button size="xs" variant="outline" onClick={() => void api.runJobNow(job.id).then(load)}>
                <Play className="size-3" />
                Run now
              </Button>
              <Button
                size="xs"
                variant="outline"
                onClick={() => void api.patchJob(job.id, { enabled: !job.enabled }).then(load)}
              >
                {job.enabled ? "Pause" : "Resume"}
              </Button>
              <Button
                size="xs"
                variant="ghost"
                onClick={async () => {
                  if (!confirm(`Delete job "${job.name}"?`)) return;
                  await api.deleteJob(job.id);
                  await load();
                }}
              >
                <Trash2 className="size-3.5 text-danger" />
              </Button>
            </div>
          </li>
        ))}
        {jobs.length === 0 ? (
          <p className="py-3 text-center text-[12.5px] text-muted-foreground">No scheduled jobs yet.</p>
        ) : null}
      </ul>

      {formOpen ? (
        <div className="space-y-2.5 rounded-xl border border-border bg-surface p-3.5">
          <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="Job name (e.g. Morning health check)" className="h-8 text-xs" />
          <textarea
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            rows={3}
            placeholder="What should the agent do each run?"
            className="w-full rounded-lg border border-input bg-surface px-3 py-2 text-[12.5px] focus:outline-none"
          />
          <div className="flex gap-2">
            <select
              value={interval}
              onChange={(e) => setInterval(Number(e.target.value))}
              className="h-8 flex-1 rounded-lg border border-border bg-surface px-2 text-xs"
            >
              {INTERVALS.map(([v, label]) => (
                <option key={v} value={v}>{label}</option>
              ))}
            </select>
            <Button
              size="sm"
              disabled={!prompt.trim()}
              onClick={async () => {
                await api.createJob({
                  name: name.trim() || "Scheduled run",
                  project_id: project.id,
                  prompt: prompt.trim(),
                  interval_minutes: interval,
                });
                setName("");
                setPrompt("");
                setFormOpen(false);
                await load();
              }}
            >
              Schedule
            </Button>
          </div>
        </div>
      ) : (
        <Button variant="outline" size="sm" onClick={() => setFormOpen(true)}>
          <Plus className="size-4" />
          New scheduled job
        </Button>
      )}
    </div>
  );
}
