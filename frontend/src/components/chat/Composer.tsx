import { ArrowUp, BookOpen, Camera, Languages, LibraryBig, Loader2, Mic, NotebookPen, Paperclip, Phone, Plus, Sparkles, Square, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown";
import { api } from "@/lib/api";
import { activeProject, useStore } from "@/lib/store";
import type { SkillInfo } from "@/types";
import { cn, formatBytes } from "@/lib/utils";
import { wrapTranslate } from "@/lib/translate";
import { useVoiceAssistant } from "@/hooks/useVoiceAssistant";
import { VoiceAssistantBar } from "@/components/voice/VoiceAssistant";
import { CallMode } from "@/components/voice/CallMode";
import { PromptLibrary } from "@/components/chat/PromptLibrary";

type CommandOrSkill = {
  name: string;
  description: string;
  enabled?: boolean;
  source?: string;
};

const CLAUDE_CODE_COMMANDS: CommandOrSkill[] = [
  { name: "commit", description: "Inspect git diff and make a conventional git commit", enabled: true, source: "builtin" },
  { name: "review", description: "Deep code review, bug inspection, and security audit", enabled: true, source: "builtin" },
  { name: "compact", description: "Compress conversation context history", enabled: true, source: "builtin" },
  { name: "cost", description: "Show token counts and exact USD cost breakdown", enabled: true, source: "builtin" },
  { name: "doctor", description: "Diagnose workspace environment and tools health", enabled: true, source: "builtin" },
  { name: "diff", description: "Show current workspace git diff", enabled: true, source: "builtin" },
  { name: "tasks", description: "View active tasks and todo progress", enabled: true, source: "builtin" },
  { name: "memory", description: "Show long-term workspace memories", enabled: true, source: "builtin" },
  { name: "clear", description: "Clear current chat history", enabled: true, source: "builtin" },
  { name: "help", description: "Show available commands and agent tools", enabled: true, source: "builtin" },
];

const SUGGESTIONS = [
  "Is repo ka structure samjha kar batao",
  "Add a REST endpoint and a test for it",
  "Find and fix the bug in the auth flow",
  "Build a landing page and preview it",
];

function MentionPanel({
  query,
  matches,
  fallback,
  activeIndex,
  totalSkills,
  anchor,
  onSelect,
  onHover,
  onClose,
}: {
  query: string;
  matches: CommandOrSkill[];
  fallback: boolean;
  activeIndex: number;
  totalSkills: number;
  anchor: { left: number; bottom: number; width: number };
  onSelect: (name: string) => void;
  onHover: (index: number) => void;
  onClose: () => void;
}) {
  const active = matches.length > 0 ? activeIndex % matches.length : 0;
  // Portalled to document.body with fixed positioning: the composer lives
  // inside overflow-hidden ancestors that would clip an absolutely
  // positioned panel, leaving users staring at nothing after typing "/".
  return createPortal(
    <div
      style={{ position: "fixed", left: anchor.left, bottom: anchor.bottom, width: anchor.width }}
      className="z-50 overflow-hidden rounded-xl border border-border bg-elevated shadow-xl animate-message-in"
    >
      <div className="flex items-center justify-between border-b border-border px-3 py-1.5">
        <p className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
          {fallback ? `No match for "/${query}" — all skills` : "Skills — the agent follows the selected one"}
        </p>
        <button
          type="button"
          onClick={onClose}
          className="rounded p-0.5 text-muted-foreground hover:text-foreground"
          title="Close (Esc)"
        >
          <X className="size-3.5" />
        </button>
      </div>
      {matches.length === 0 ? (
        <p className="px-3 py-3 text-[12.5px] text-muted-foreground">
          {totalSkills === 0
            ? "No skills installed yet — add some in Settings → Skills."
            : `No skill matches "/${query}".`}
        </p>
      ) : (
        <ul className="scrollbar-thin max-h-56 overflow-y-auto p-1">
          {matches.map((skill, i) => (
            <li key={skill.name}>
              <button
                type="button"
                onMouseDown={(e) => e.preventDefault()}
                onMouseEnter={() => onHover(i)}
                onClick={() => onSelect(skill.name)}
                className={cn(
                  "flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 text-left transition-colors",
                  i === active ? "bg-accent text-accent-foreground" : "hover:bg-accent/60",
                  !skill.enabled && "opacity-55",
                )}
              >
                <BookOpen className="size-3.5 shrink-0 text-primary" />
                <span className="min-w-0 flex-1">
                  <span className="block truncate font-mono text-[12.5px]">/{skill.name}</span>
                  <span className="block truncate text-[11px] text-muted-foreground">
                    {skill.description}
                  </span>
                </span>
                {!skill.enabled ? (
                  <span className="shrink-0 text-[10.5px] text-muted-foreground">off</span>
                ) : null}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>,
    document.body,
  );
}

function MenuAction({
  icon: Icon,
  title,
  desc,
  disabled,
  onSelect,
}: {
  icon: typeof Paperclip;
  title: string;
  desc: string;
  disabled?: boolean;
  onSelect: () => void;
}) {
  return (
    // NOTE: no preventDefault here — Radix closes the menu on select by
    // default, and preventing it left the menu stuck open after every tap.
    <DropdownMenuItem disabled={disabled} onSelect={onSelect}>
      <Icon className="size-4 shrink-0 text-muted-foreground" />
      <span className="min-w-0">
        <span className="block text-[13px] font-medium leading-tight">{title}</span>
        <span className="block truncate text-[11px] text-muted-foreground">{desc}</span>
      </span>
    </DropdownMenuItem>
  );
}

export function Composer({ showSuggestions }: { showSuggestions?: boolean }) {
  const [value, setValue] = useState("");
  const [uploading, setUploading] = useState(false);
  const [attachments, setAttachments] = useState<{ name: string; path: string; size: number }[]>([]);
  const [libraryOpen, setLibraryOpen] = useState(false);
  const [callOpen, setCallOpen] = useState(false);
  const [plusOpen, setPlusOpen] = useState(false);
  const [dictating, setDictating] = useState(false);
  const [notes, setNotes] = useState("");
  const dictatingRef = useRef(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const cameraRef = useRef<HTMLInputElement>(null);

  // ---- skills (/mention to invoke — the agent force-loads the skill) ----
  const project = useStore(activeProject);
  const [skills, setSkills] = useState<SkillInfo[]>([]);
  const [mention, setMention] = useState<{ query: string } | null>(null);
  const [mentionIndex, setMentionIndex] = useState(0);
  const [anchor, setAnchor] = useState<{ left: number; bottom: number; width: number } | null>(null);
  const skillsLoading = useRef(false);

  const loadSkills = async () => {
    if (!project || skillsLoading.current) return;
    skillsLoading.current = true;
    try {
      setSkills(await api.listSkills(project.id).catch(() => []));
    } finally {
      skillsLoading.current = false;
    }
  };

  useEffect(() => {
    void loadSkills();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [project?.id]);

  // Name + description search; a query with zero hits falls back to the
  // full list so "/" always shows something pickable when skills exist.
  const mentionMatches = (query: string): { list: CommandOrSkill[]; fallback: boolean } => {
    const q = query.toLowerCase();
    const allAvailable = [...CLAUDE_CODE_COMMANDS, ...skills];
    const hits = allAvailable
      .filter((s) => s.name.includes(q) || s.description.toLowerCase().includes(q))
      .slice(0, 10);
    if (hits.length === 0 && allAvailable.length > 0) return { list: allAvailable.slice(0, 10), fallback: true };
    return { list: hits, fallback: false };
  };

  const updateAnchor = () => {
    const el = textareaRef.current;
    if (!el) return;
    const rect = el.getBoundingClientRect();
    setAnchor({
      left: Math.max(8, Math.min(rect.left, window.innerWidth - 200)),
      bottom: Math.max(8, window.innerHeight - rect.top + 8),
      width: Math.max(200, Math.min(rect.width, 440)),
    });
  };

  // Keep the floating panel glued to the textarea across scroll/resize.
  useEffect(() => {
    if (!mention) return;
    updateAnchor();
    window.addEventListener("resize", updateAnchor);
    window.addEventListener("scroll", updateAnchor, true);
    return () => {
      window.removeEventListener("resize", updateAnchor);
      window.removeEventListener("scroll", updateAnchor, true);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mention, value]);

  const refreshMention = (text: string, cursor: number | null) => {
    if (cursor === null) {
      setMention(null);
      return;
    }
    const match = /(^|\s)\/([a-z0-9-]*)$/.exec(text.slice(0, cursor));
    if (match) {
      if (skills.length === 0) void loadSkills();
      updateAnchor();
      setMention({ query: match[2] });
      setMentionIndex(0);
    } else {
      setMention(null);
    }
  };

  const insertSkill = (name: string) => {
    const el = textareaRef.current;
    const cursor = el?.selectionStart ?? value.length;
    const before = value.slice(0, cursor).replace(/(^|\s)\/[a-z0-9-]*$/, `$1/${name} `);
    const next = before + value.slice(cursor);
    setValue(next);
    setMention(null);
    requestAnimationFrame(() => {
      el?.focus();
      el?.setSelectionRange(before.length, before.length);
    });
  };

  const openSkillPicker = () => {
    void loadSkills();
    const el = textareaRef.current;
    el?.focus();
    setValue((prev) => {
      const next = prev && !prev.endsWith(" ") && !prev.endsWith("\n") ? `${prev} /` : `${prev}/`;
      requestAnimationFrame(() => {
        const pos = next.length;
        el?.setSelectionRange(pos, pos);
        refreshMention(next, pos);
      });
      return next;
    });
  };

  const running = useStore((s) => s.running);
  const threadId = useStore((s) => s.activeThreadId);
  const send = useStore((s) => s.send);
  const interrupt = useStore((s) => s.interrupt);
  const translateMode = useStore((s) => s.translateMode);
  const translateTarget = useStore((s) => s.translateTarget);

  const submitText = async (textToSend: string) => {
    const text = textToSend.trim();
    if (!text || !threadId) return;
    const translated = wrapTranslate(text, translateMode, translateTarget);
    const withFiles = attachments.length
      ? `${translated}\n\nAttached files in the workspace:\n${attachments.map((a) => `- ${a.path}`).join("\n")}`
      : translated;
    setValue("");
    setAttachments([]);
    await send(withFiles);
  };

  const toggleDictation = () => {
    const next = !dictating;
    setDictating(next);
    dictatingRef.current = next;
    if (next) {
      voice.startListening();
    } else {
      voice.stopListening();
    }
  };

  const structureNotes = async () => {
    const text = notes.trim();
    if (!text) return;
    setNotes("");
    setDictating(false);
    dictatingRef.current = false;
    voice.stopListening();
    await submitText(
      `[Dictation] Convert the following raw dictated notes into structured notes with headings, key points, action items and deadlines:\n\n${text}`,
    );
  };

  const voice = useVoiceAssistant({
    enableWake: true,
    onTranscript: (spokenText) => {
      // Dictation mode accumulates into the notes pad instead of the composer.
      if (dictatingRef.current) {
        setNotes((prev) => (prev ? `${prev} ${spokenText}` : spokenText));
        return;
      }
      setValue((prev) => (prev ? `${prev} ${spokenText}` : spokenText));
    },
    onSend: (spokenText) => {
      // While dictating, finals stay in the notes pad — never auto-send.
      if (dictatingRef.current) return;
      setValue(spokenText);
      void submitText(spokenText);
    },
  });

  const submit = async () => {
    await submitText(value);
  };

  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 260)}px`;
  }, [value]);

  // Shared drafts (PWA share-target, plan revisions, palette): merge in live.
  const draft = useStore((s) => s.draft);
  const consumeDraft = useStore((s) => s.consumeDraft);
  useEffect(() => {
    if (draft) {
      setValue((prev) => (prev ? `${prev}\n${draft}` : draft));
      consumeDraft();
      textareaRef.current?.focus();
    }
  }, [draft, consumeDraft]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "/" && document.activeElement?.tagName !== "TEXTAREA") {
        event.preventDefault();
        textareaRef.current?.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const upload = async (files: FileList | null) => {
    if (!files?.length || !threadId) return;
    setUploading(true);
    try {
      for (const file of Array.from(files)) {
        const result = await api.uploadFile(threadId, file);
        setAttachments((prev) => [...prev, { name: result.name, path: result.path, size: result.size }]);
      }
    } finally {
      setUploading(false);
    }
  };

  const matchInfo = mention ? mentionMatches(mention.query) : { list: [] as SkillInfo[], fallback: false };

  return (
    <div className="space-y-3 w-full max-w-full overflow-hidden">
      {/* Voice Assistant Live Status Wave Bar */}
      <VoiceAssistantBar voice={voice} />
      {callOpen ? <CallMode voice={voice} onClose={() => setCallOpen(false)} /> : null}
      <PromptLibrary
        open={libraryOpen}
        onOpenChange={setLibraryOpen}
        onInsert={(text) => setValue((prev) => (prev ? `${prev}\n${text}` : text))}
      />

      {mention && anchor ? (
        <MentionPanel
          query={mention.query}
          matches={matchInfo.list}
          fallback={matchInfo.fallback}
          activeIndex={mentionIndex}
          totalSkills={skills.length}
          anchor={anchor}
          onSelect={insertSkill}
          onHover={setMentionIndex}
          onClose={() => setMention(null)}
        />
      ) : null}

      {showSuggestions && !value && (
        <div className="flex flex-wrap justify-center gap-2">
          {SUGGESTIONS.map((s, i) => (
            <button
              key={s}
              type="button"
              onClick={() => setValue(s)}
              style={{ animationDelay: `${i * 70}ms` }}
              className="rise-stagger rounded-full border border-border bg-surface px-3 py-1.5 text-[13px] text-muted-foreground text-center transition-all hover:-translate-y-0.5 hover:border-primary/40 hover:text-foreground hover:shadow-md"
            >
              {s}
            </button>
          ))}
        </div>
      )}

      <div
        className={cn(
          "composer-shell relative rounded-2xl border border-border bg-surface shadow-sm w-full",
        )}
        onDragOver={(e) => e.preventDefault()}
        onDrop={(e) => {
          e.preventDefault();
          void upload(e.dataTransfer.files);
        }}
      >
        {attachments.length > 0 && (
          <div className="flex flex-wrap gap-1.5 border-b border-border px-3 py-2">
            {attachments.map((a) => (
              <span
                key={a.path}
                className="inline-flex items-center gap-1.5 rounded-md bg-muted px-2 py-1 text-[11px]"
              >
                <span className="font-mono">{a.name}</span>
                <span className="text-muted-foreground">{formatBytes(a.size)}</span>
                <button
                  type="button"
                  onClick={() => setAttachments((prev) => prev.filter((x) => x.path !== a.path))}
                >
                  <X className="size-3 text-muted-foreground hover:text-foreground" />
                </button>
              </span>
            ))}
          </div>
        )}

        <textarea
          ref={textareaRef}
          value={value}
          onChange={(e) => {
            setValue(e.target.value);
            refreshMention(e.target.value, e.target.selectionStart);
          }}
          onClick={(e) => refreshMention(value, e.currentTarget.selectionStart)}
          onFocus={() => {
            void loadSkills();
            const el = textareaRef.current;
            if (el) refreshMention(el.value, el.selectionStart);
          }}
          onKeyDown={(e) => {
            const matches = matchInfo.list;
            if (mention) {
              if (e.key === "ArrowDown" || e.key === "ArrowUp") {
                e.preventDefault();
                setMentionIndex((i) => (i + (e.key === "ArrowDown" ? 1 : -1) + matches.length) % Math.max(matches.length, 1));
                return;
              }
              if ((e.key === "Enter" || e.key === "Tab") && matches.length > 0) {
                e.preventDefault();
                insertSkill(matches[mentionIndex % matches.length].name);
                return;
              }
              if (e.key === "Escape") {
                e.preventDefault();
                setMention(null);
                return;
              }
            }
            if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault();
              void submit();
            }
          }}
          rows={1}
          placeholder={running ? "Agent is working — type to steer it…" : "Ask anything, build, or type / for skills…"}
          className="scrollbar-thin max-h-[260px] w-full resize-none bg-transparent px-4 pt-3.5 text-[15px] leading-relaxed placeholder:text-muted-foreground focus:outline-none"
        />

        {dictating ? (
          <div className="mx-3 mb-1 rounded-xl border border-primary/30 bg-primary/5 p-3 animate-message-in">
            <div className="mb-1.5 flex items-center justify-between">
              <p className="flex items-center gap-1.5 text-[12px] font-medium text-primary">
                <span className="size-2 animate-glow-pulse rounded-full bg-danger" />
                Dictating… speak freely
                <span className="tabular-nums text-muted-foreground">
                  {notes.trim() ? `${notes.trim().split(/\s+/).length} words` : "0 words"}
                </span>
              </p>
              <button
                type="button"
                onClick={() => {
                  setNotes("");
                  setDictating(false);
                  dictatingRef.current = false;
                  voice.stopListening();
                }}
                className="text-[11.5px] text-muted-foreground hover:text-danger"
              >
                Discard
              </button>
            </div>
            <p className="scrollbar-thin max-h-28 min-h-10 overflow-y-auto whitespace-pre-wrap text-[13.5px] leading-relaxed">
              {notes || <span className="italic text-muted-foreground">Your words appear here…</span>}
              {voice.state === "listening" ? <span className="streaming-caret" /> : null}
            </p>
            <div className="mt-2 flex justify-end">
              <Button size="sm" disabled={!notes.trim() || running} onClick={() => void structureNotes()} className="glow-soft">
                <Sparkles className="size-3.5" />
                Structure with AI
              </Button>
            </div>
          </div>
        ) : null}

        <div className="flex items-center justify-between gap-2 px-2.5 pb-2.5 pt-1">
          <div className="flex items-center gap-1">
            <input
              ref={fileRef}
              type="file"
              multiple
              className="hidden"
              onChange={(e) => void upload(e.target.files)}
            />
            <input
              ref={cameraRef}
              type="file"
              accept="image/*"
              capture="environment"
              className="hidden"
              onChange={(e) => void upload(e.target.files)}
            />
            <DropdownMenu
              open={plusOpen}
              onOpenChange={(open) => {
                setPlusOpen(open);
                if (open) void loadSkills();
              }}
            >
              <DropdownMenuTrigger asChild>
                <Button
                  variant={plusOpen ? "secondary" : "ghost"}
                  size="icon-sm"
                  title="Attach, speak, skills…"
                  disabled={!threadId && !voice.supported}
                >
                  {uploading ? (
                    <Loader2 className="size-4 animate-spin" />
                  ) : (
                    <Plus
                      className={cn(
                        "size-4 transition-transform duration-200",
                        plusOpen && "rotate-45 scale-110",
                      )}
                    />
                  )}
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent side="top" align="start" className="w-64">
                <DropdownMenuLabel>Attach</DropdownMenuLabel>
                <DropdownMenuGroup>
                  <MenuAction
                    icon={Paperclip}
                    title="Upload files"
                    desc="Docs, images, data…"
                    disabled={uploading || !threadId}
                    onSelect={() => fileRef.current?.click()}
                  />
                  <MenuAction
                    icon={Camera}
                    title="Take photo"
                    desc="Mobile camera capture"
                    disabled={uploading || !threadId}
                    onSelect={() => cameraRef.current?.click()}
                  />
                </DropdownMenuGroup>
                <DropdownMenuSeparator />
                <DropdownMenuLabel>Voice</DropdownMenuLabel>
                <DropdownMenuGroup>
                  <MenuAction
                    icon={NotebookPen}
                    title="Dictate notes"
                    desc="Speak → structured with AI"
                    disabled={!threadId || !voice.supported}
                    onSelect={toggleDictation}
                  />
                  <MenuAction
                    icon={Phone}
                    title="Live voice call"
                    desc="Talk with the agent"
                    disabled={!threadId}
                    onSelect={() => setCallOpen(true)}
                  />
                  <MenuAction
                    icon={Mic}
                    title={voice.state === "listening" ? "Stop listening" : "Voice input"}
                    desc="Hands-free dictation"
                    disabled={!voice.supported}
                    onSelect={() => voice.toggleListening()}
                  />
                </DropdownMenuGroup>
                <DropdownMenuSeparator />
                <DropdownMenuLabel>Knowledge</DropdownMenuLabel>
                <DropdownMenuGroup>
                  <MenuAction
                    icon={LibraryBig}
                    title="Prompt library"
                    desc="Personas & templates"
                    onSelect={() => setLibraryOpen(true)}
                  />
                  <MenuAction
                    icon={BookOpen}
                    title="Use a skill"
                    desc={
                      skills.length > 0
                        ? `${skills.length} installed — agent follows it`
                        : "Type / or pick — agent follows it"
                    }
                    onSelect={openSkillPicker}
                  />
                </DropdownMenuGroup>
              </DropdownMenuContent>
            </DropdownMenu>

            {translateMode ? (
              <span className="hidden items-center gap-1 rounded-full bg-primary/10 px-2 py-0.5 text-[10.5px] font-medium text-primary sm:inline-flex">
                <Languages className="size-3" />
                {translateTarget === "en" ? "→ EN" : "→ HI"}
              </span>
            ) : null}

            <span className="hidden text-[11px] text-muted-foreground sm:block">
              Enter to send · Shift+Enter for a new line
            </span>
          </div>

          {running ? (
            <Button
              key="stop"
              variant="secondary"
              size="sm"
              onClick={() => void interrupt()}
              className="animate-scale-in"
            >
              <Square className="size-3.5 fill-current animate-glow-pulse" />
              Stop
            </Button>
          ) : (
            <Button
              key="send"
              size="icon-sm"
              onClick={() => void submit()}
              disabled={!value.trim() || !threadId}
              className="animate-scale-in transition-transform hover:scale-105 active:scale-95 disabled:hover:scale-100"
            >
              <ArrowUp className="size-4" />
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}
