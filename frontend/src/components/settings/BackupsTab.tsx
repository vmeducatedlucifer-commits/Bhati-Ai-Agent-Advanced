import { Archive, Camera, Copy, Database, GitBranch, Github, HardDriveDownload, Rocket, RotateCcw, Trash2, UploadCloud, Webhook } from "lucide-react";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api";
import { activeProject, useStore } from "@/lib/store";
import { formatBytes, relativeTime } from "@/lib/utils";

interface Snapshot {
  name: string;
  size: number;
  created_at: string;
}

export function BackupsTab() {
  const project = useStore(activeProject);
  const refreshProjects = useStore((s) => s.refreshProjects);
  const selectProject = useStore((s) => s.selectProject);
  const [storage, setStorage] = useState<{ bytes: number; files: number } | null>(null);
  const [snapshots, setSnapshots] = useState<Snapshot[]>([]);
  const [label, setLabel] = useState("");
  const [cloneName, setCloneName] = useState("");
  const [pushing, setPushing] = useState(false);
  const [pushRepo, setPushRepo] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = async () => {
    if (!project) return;
    setStorage(await api.projectStorage(project.id).catch(() => null));
    setSnapshots(await api.listSnapshots(project.id).catch(() => []));
  };

  useEffect(() => {
    setPushRepo(null);
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [project?.id]);

  if (!project) return <p className="text-[13px] text-muted-foreground">Create a project first.</p>;

  const copy = (text: string) => void navigator.clipboard?.writeText(text);
  const webhookUrl = `${window.location.origin.replace(/:\d+$/, ":8000")}/api/v1/webhooks/github?project_id=${project.id}&token=YOUR_SECRET`;

  return (
    <div className="space-y-5">
      {/* storage meter */}
      <div className="rounded-xl border border-border bg-surface p-4">
        <p className="mb-2 flex items-center gap-2 text-xs font-medium">
          <Database className="size-3.5 text-primary" />
          Workspace storage
        </p>
        {storage ? (
          <>
            <p className="text-[13px]">
              <span className="font-semibold">{formatBytes(storage.bytes)}</span>
              <span className="text-muted-foreground"> · {storage.files.toLocaleString()} files</span>
            </p>
            <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-muted">
              <div
                className="h-full rounded-full bg-primary transition-all"
                style={{ width: `${Math.min(100, (storage.bytes / (500 * 1024 * 1024)) * 100)}%` }}
              />
            </div>
            <p className="mt-1 text-[10.5px] text-muted-foreground">ZIP downloads cap at 500 MB per archive.</p>
          </>
        ) : (
          <div className="skeleton h-8 w-full" />
        )}
      </div>

      {/* snapshots */}
      <div className="rounded-xl border border-border bg-surface p-4">
        <p className="mb-1 flex items-center gap-2 text-xs font-medium">
          <Camera className="size-3.5 text-primary" />
          Snapshots — 1-click rollback points
        </p>
        <p className="mb-3 text-[11px] text-muted-foreground">Stored on the backend, independent of Google Drive.</p>
        <div className="mb-3 flex gap-2">
          <Input value={label} onChange={(e) => setLabel(e.target.value)} placeholder="Label (optional)" className="h-8 text-xs" />
          <Button
            size="sm"
            disabled={busy}
            onClick={async () => {
              setBusy(true);
              try {
                await api.createSnapshot(project.id, label.trim());
                setLabel("");
                await load();
              } finally {
                setBusy(false);
              }
            }}
          >
            Take snapshot
          </Button>
        </div>
        <ul className="space-y-1.5">
          {snapshots.map((s) => (
            <li key={s.name} className="flex items-center gap-2 rounded-lg border border-border px-3 py-2">
              <Archive className="size-3.5 shrink-0 text-muted-foreground" />
              <div className="min-w-0 flex-1">
                <p className="truncate font-mono text-[12px]">{s.name}</p>
                <p className="text-[10.5px] text-muted-foreground">{formatBytes(s.size)} · {relativeTime(s.created_at)}</p>
              </div>
              <Button
                size="xs"
                variant="outline"
                onClick={async () => {
                  if (!confirm(`Restore snapshot "${s.name}"? Current files will be overwritten.`)) return;
                  await api.restoreSnapshot(project.id, s.name);
                }}
              >
                <RotateCcw className="size-3" />
                Restore
              </Button>
              <Button size="xs" variant="ghost" onClick={() => void api.deleteSnapshot(project.id, s.name).then(load)}>
                <Trash2 className="size-3.5 text-danger" />
              </Button>
            </li>
          ))}
          {snapshots.length === 0 ? (
            <p className="py-2 text-center text-[12px] text-muted-foreground">No snapshots yet.</p>
          ) : null}
        </ul>
      </div>

      {/* clone + download */}
      <div className="rounded-xl border border-border bg-surface p-4">
        <p className="mb-3 flex items-center gap-2 text-xs font-medium">
          <Copy className="size-3.5 text-primary" />
          Clone & download
        </p>
        <div className="mb-2 flex gap-2">
          <Input value={cloneName} onChange={(e) => setCloneName(e.target.value)} placeholder="Clone name" className="h-8 text-xs" />
          <Button
            size="sm"
            variant="outline"
            disabled={!cloneName.trim()}
            onClick={async () => {
              const res = await api.cloneProject(project.id, cloneName.trim());
              setCloneName("");
              await refreshProjects();
              await selectProject(res.id);
            }}
          >
            Clone
          </Button>
        </div>
        <Button size="sm" variant="outline" onClick={() => void api.downloadProjectZip(project.id, `${project.name}.zip`)}>
          <HardDriveDownload className="size-3.5" />
          Download full project ZIP
        </Button>
      </div>

      {/* github push */}
      <div className="rounded-xl border border-border bg-surface p-4">
        <p className="mb-1 flex items-center gap-2 text-xs font-medium">
          <Github className="size-3.5 text-primary" />
          Push to GitHub
        </p>
        <p className="mb-3 text-[11px] text-muted-foreground">Commits and force-pushes the workspace to main. Needs a token in Connectors.</p>
        <Button
          size="sm"
          disabled={pushing}
          onClick={async () => {
            setPushing(true);
            try {
              const res = await api.pushProject(project.id);
              setPushRepo(res.repo);
            } catch {
              setPushRepo(null);
            } finally {
              setPushing(false);
            }
          }}
        >
          <UploadCloud className="size-3.5" />
          {pushing ? "Pushing…" : "Push now"}
        </Button>
        {pushRepo ? (
          <p className="mt-2 flex items-center gap-1.5 font-mono text-[11.5px] text-emerald-500">
            <GitBranch className="size-3" />
            {pushRepo}
          </p>
        ) : null}
      </div>

      {/* deploy */}
      <div className="rounded-xl border border-border bg-surface p-4">
        <p className="mb-1 flex items-center gap-2 text-xs font-medium">
          <Rocket className="size-3.5 text-primary" />
          1-click deploy guides
        </p>
        <p className="mb-3 text-[11px] text-muted-foreground">Opens the provider with this repo pre-selected.</p>
        <div className="flex flex-wrap gap-2">
          <Button size="sm" variant="outline" onClick={() => window.open("https://vercel.com/new", "_blank")}>
            Deploy frontend on Vercel
          </Button>
          <Button size="sm" variant="outline" onClick={() => window.open("https://render.com", "_blank")}>
            Deploy backend on Render
          </Button>
          <Button size="sm" variant="ghost" onClick={() => copy("VITE_API_URL=https://<your-render-backend>/api/v1")}>
            <Copy className="size-3.5" />
            Copy env line
          </Button>
        </div>
      </div>

      {/* webhook */}
      <div className="rounded-xl border border-border bg-surface p-4">
        <p className="mb-1 flex items-center gap-2 text-xs font-medium">
          <Webhook className="size-3.5 text-primary" />
          GitHub push webhook
        </p>
        <p className="mb-2 text-[11px] text-muted-foreground">
          Add this URL in repo Settings → Webhooks. Set GITHUB_WEBHOOK_SECRET on the backend first.
        </p>
        <div className="flex items-center gap-2">
          <code className="min-w-0 flex-1 truncate rounded-lg bg-muted px-2.5 py-1.5 font-mono text-[10.5px]">{webhookUrl}</code>
          <Button size="xs" variant="outline" onClick={() => copy(webhookUrl)}>
            <Copy className="size-3.5" />
          </Button>
        </div>
      </div>
    </div>
  );
}
