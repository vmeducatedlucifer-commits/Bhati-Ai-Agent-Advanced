"""The agent loop.

One `AgentRunner` per turn. It streams deltas from the model, executes tool calls,
publishes every observable step to the event bus, and persists the result so a reload
reproduces the conversation exactly.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.context import compact, estimate_tokens, needs_compaction
from app.agent.permissions import args_fingerprint, permissions
from app.agent.prompts import TITLE_PROMPT, build_system_prompt
from app.core.config import settings
from app.core.events import bus
from app.core.logging import get_logger
from app.core.utils import new_id, truncate
from app.db.models import Message, Project, Thread, ToolCallRecord, UsageStat
from app.db.session import SessionLocal
from app.llm import LLMError, resolve_model
from app.llm.types import ToolCall
from app.sandbox import sandboxes
from app.tools import registry
from app.tools.base import ToolContext, ToolResult

log = get_logger("app.agent")

TOOL_RESULT_LIMIT = 30_000
PARALLEL_SAFE_GROUPS = {"files", "search", "web", "git", "memory"}


class RunRegistry:
    """Tracks in-flight runs so the API can interrupt or steer them immediately."""

    def __init__(self) -> None:
        self._cancels: dict[str, asyncio.Event] = {}
        self._tasks: dict[str, asyncio.Task] = {}
        self._queued: dict[str, list[str]] = {}

    def begin(self, thread_id: str) -> asyncio.Event:
        """Claim a thread, adopting an early API-side reservation if present."""
        existing = self._cancels.get(thread_id)
        if existing is not None:
            return existing
        event = asyncio.Event()
        self._cancels[thread_id] = event
        return event

    def reserve(self, thread_id: str) -> bool:
        """Reserve an idle thread before its asyncio task is scheduled."""
        if thread_id in self._cancels:
            return False
        self._cancels[thread_id] = asyncio.Event()
        return True

    def register_task(self, thread_id: str, task: asyncio.Task) -> None:
        self._tasks[thread_id] = task

    def end(self, thread_id: str) -> None:
        self._cancels.pop(thread_id, None)
        self._tasks.pop(thread_id, None)
        self._queued.pop(thread_id, None)

    def is_running(self, thread_id: str) -> bool:
        return thread_id in self._cancels

    def cancel(self, thread_id: str) -> bool:
        event = self._cancels.get(thread_id)
        task = self._tasks.get(thread_id)
        if event is None and task is None:
            return False

        if event is not None:
            event.set()

        # Unblock any pending user permission prompts immediately
        try:
            permissions.clear(thread_id)
        except Exception:
            pass

        if task is not None and not task.done():
            task.cancel()

        return True

    def steer(self, thread_id: str, text: str) -> bool:
        """Inject a mid-run instruction; picked up before the next model call."""
        if thread_id not in self._cancels:
            return False
        self._queued.setdefault(thread_id, []).append(text)
        return True

    def take_steering(self, thread_id: str) -> list[str]:
        return self._queued.pop(thread_id, [])


runs = RunRegistry()


class Interrupted(Exception):
    pass


class AgentRunner:
    def __init__(
        self,
        *,
        thread: Thread,
        project: Project,
        depth: int = 0,
        parent_ctx: ToolContext | None = None,
    ):
        self.thread = thread
        self.project = project
        self.thread_id = thread.id
        self.topic = f"thread:{thread.id}"
        self.depth = depth
        self.parent_ctx = parent_ctx
        self.cancel_event: asyncio.Event | None = None
        self.state: dict[str, Any] = {"todos": list(thread.todos or [])}
        self.usage = {"prompt_tokens": 0, "completion_tokens": 0}
        # Loop-pathology guard: identical consecutive tool-call sets.
        self._last_tool_fp: tuple | None = None
        self._repeat_count = 0
        self._browser_recovery_count = 0

    # ---- plumbing --------------------------------------------------------

    async def emit(self, type_: str, payload: dict[str, Any] | None = None) -> None:
        if self.depth > 0 and self.parent_ctx is not None:
            # Nested runs surface through the parent's tool-call frame.
            await bus.publish(
                self.topic,
                {
                    "type": "subagent_event",
                    "thread_id": self.thread_id,
                    "tool_call_id": self.parent_ctx.tool_call_id,
                    "event": {"type": type_, **(payload or {})},
                },
            )
            return
        await bus.publish(self.topic, {"type": type_, "thread_id": self.thread_id, **(payload or {})})

    def _check_cancel(self) -> None:
        if self.cancel_event is not None and self.cancel_event.is_set():
            raise Interrupted()

    def _check_repeat(self, tool_calls: list[ToolCall]) -> str | None:
        """Detect a looped model: identical tool-call sets 3 steps running.

        Returns an error message for the UI when tripped, else None.
        """
        fp = tuple(sorted((tc.name, args_fingerprint(tc.arguments)) for tc in tool_calls))
        if fp == self._last_tool_fp:
            self._repeat_count += 1
        else:
            self._last_tool_fp = fp
            self._repeat_count = 1
        if self._repeat_count >= 3:
            return (
                f"Stopped: `{tool_calls[0].name}` was repeated 3 times with the same "
                "arguments. Rephrase the request or intervene."
            )
        return None

    # ---- history ---------------------------------------------------------

    async def _load_history(self, db: AsyncSession) -> list[dict[str, Any]]:
        rows = (
            await db.execute(
                select(Message).where(Message.thread_id == self.thread_id).order_by(Message.position)
            )
        ).scalars().all()
        history: list[dict[str, Any]] = []
        for row in rows:
            if row.raw:
                history.append(row.raw)
            elif row.role in ("user", "assistant"):
                history.append({"role": row.role, "content": row.content})
        return history

    async def _next_position(self, db: AsyncSession) -> int:
        value = (
            await db.execute(
                select(func.coalesce(func.max(Message.position), -1)).where(
                    Message.thread_id == self.thread_id
                )
            )
        ).scalar_one()
        return int(value) + 1

    async def _save_message(
        self,
        db: AsyncSession,
        *,
        role: str,
        content: str,
        raw: dict[str, Any],
        message_id: str | None = None,
        reasoning: str = "",
        attachments: list[dict[str, Any]] | None = None,
        meta: dict[str, Any] | None = None,
        error: str = "",
    ) -> Message:
        message = Message(
            id=message_id or new_id("msg"),
            thread_id=self.thread_id,
            position=await self._next_position(db),
            role=role,
            content=content,
            reasoning=reasoning,
            raw=raw,
            attachments=attachments or [],
            meta=meta or {},
            error=error,
        )
        db.add(message)
        await db.commit()
        return message

    # ---- main entry ------------------------------------------------------

    async def run(self, user_text: str, attachments: list[dict[str, Any]] | None = None) -> None:
        self.cancel_event = runs.begin(self.thread_id)
        if asyncio.current_task():
            runs.register_task(self.thread_id, asyncio.current_task())

        started = time.time()
        try:
            await self._run_inner(user_text, attachments or [])
        except (Interrupted, asyncio.CancelledError):
            log.info("Agent run interrupted/cancelled on thread %s", self.thread_id)
            await self.emit("interrupted", {})
            await self._set_status("idle")
        except LLMError as exc:
            detail = f"{exc}"
            if exc.body:
                detail += f"\n{truncate(exc.body, 800)}"
            log.warning("llm error on %s: %s", self.thread_id, detail)
            await self.emit("error", {"message": detail, "kind": "llm"})
            await self._set_status("error")
        except Exception as exc:
            log.exception("agent run failed on %s", self.thread_id)
            await self.emit("error", {"message": f"{type(exc).__name__}: {exc}", "kind": "internal"})
            await self._set_status("error")
        finally:
            runs.end(self.thread_id)
            # Sync workspace to Google Drive and GitHub in the background
            try:
                from app.storage import gdrive_manager, github_manager
                if gdrive_manager.enabled:
                    asyncio.create_task(self._backup_gdrive())
                if github_manager.enabled:
                    repo_slug = getattr(self.project, "github_repo", "")
                    asyncio.create_task(
                        github_manager.sync_workspace(
                            self.project.id,
                            self.project.workspace_path,
                            repo_slug if repo_slug else None
                        )
                    )
            except Exception:
                pass

            await self.emit(
                "run_end",
                {"duration_ms": int((time.time() - started) * 1000), "usage": self.usage},
            )

    async def _backup_gdrive(self) -> None:
        """Run a Drive backup and persist the returned file_id on the project row."""
        try:
            from app.storage import gdrive_manager
            file_id = await gdrive_manager.backup_workspace(
                self.project.id,
                self.project.workspace_path,
                getattr(self.project, "gdrive_file_id", ""),
            )
            if file_id and file_id != getattr(self.project, "gdrive_file_id", ""):
                self.project.gdrive_file_id = file_id
                async with SessionLocal() as db:
                    row = await db.get(Project, self.project.id)
                    if row:
                        row.gdrive_file_id = file_id
                        await db.commit()
        except Exception as exc:  # pragma: no cover
            log.warning("gdrive backup failed for project %s: %s", self.project.id, exc)

    async def _set_status(self, status: str) -> None:
        async with SessionLocal() as db:
            row = await db.get(Thread, self.thread_id)
            if row:
                row.status = status
                await db.commit()

    async def _run_inner(self, user_text: str, attachments: list[dict[str, Any]]) -> None:
        async with SessionLocal() as db:
            thread = await db.get(Thread, self.thread_id)
            project = await db.get(Project, self.project.id)
            resolved = await resolve_model(db, provider_id=thread.provider_id, model=thread.model)

            # Load structured memories (skills load later against this turn's text)
            from app.agent.memory import load_project_memory_prompt
            memories = load_project_memory_prompt(project.workspace_path)


            # Expand Claude Code slash commands
            expanded_text = user_text
            cmd_lower = (user_text or "").strip().lower()
            if cmd_lower.startswith("/commit"):
                extra = user_text.strip()[7:].strip()
                expanded_text = f"Inspect `git status` and `git diff` using tools. Formulate a concise conventional commit message, then stage and commit the changes. {extra}".strip()
            elif cmd_lower.startswith("/review"):
                expanded_text = "Conduct a thorough code review and security audit of the codebase and recent git changes. Inspect files, check edge cases, error handling, performance, and security issues."
            elif cmd_lower.startswith("/diff"):
                expanded_text = "Run `git diff` and `git status` using the bash tool and summarize all current workspace changes."
            elif cmd_lower.startswith("/doctor"):
                expanded_text = "Run diagnostic checks on the environment: check Python version, Node version, Git version, sandbox status, workspace disk usage, and report the health."
            elif cmd_lower.startswith("/cost"):
                expanded_text = "Check the current token usage and estimated session cost and report a clear summary."
            elif cmd_lower.startswith("/tasks") or cmd_lower.startswith("/todo"):
                expanded_text = "Review all current tasks, check todo progress, and summarize the completion status."

            if user_text:
                message = await self._save_message(
                    db,
                    role="user",
                    content=user_text,
                    raw={"role": "user", "content": expanded_text},
                    attachments=attachments,
                )
                await self.emit(
                    "message_start",
                    {"id": message.id, "role": "user", "content": user_text, "attachments": attachments},
                )

            history = await self._load_history(db)
            thread.status = "running"
            await db.commit()

        if not resolved.model:
            await self.emit(
                "error",
                {
                    "message": "No model configured. Add a provider in Settings → Models.",
                    "kind": "config",
                },
            )
            await self._set_status("idle")
            return

        sandbox = await sandboxes.get(self.thread_id, project.workspace_path)
        backend = await sandboxes.backend()
        client = resolved.client()

        mode = thread.mode or "agent"
        permission_mode = thread.permission_mode or "auto"
        read_only = mode == "plan"
        tools = [] if mode == "chat" else registry.schemas(read_only=read_only)

        # Skills: compact index always + relevant SKILL.md bodies auto-loaded
        # against this turn's text (progressive disclosure, ~30-50 tok/skill).
        # /mentioned skills are mandatory for the agent and surfaced in the feed.
        from app.agent.memory import load_skill_packs_with_meta
        skills, skills_invoked, skills_auto = await asyncio.to_thread(
            load_skill_packs_with_meta, project.workspace_path, user_text or ""
        )
        if skills:
            memories = f"{memories}\n\n{skills}" if memories else skills
        if skills_invoked or skills_auto:
            await self.emit(
                "skill",
                {
                    "skills": [
                        *( {"name": n, "mode": "invoked"} for n in skills_invoked ),
                        *( {"name": n, "mode": "auto"} for n in skills_auto ),
                    ],
                },
            )

        system_prompt = build_system_prompt(
            mode=mode,
            workspace=sandbox.workdir,
            sandbox_backend=backend,
            project_name=project.name,
            project_instructions=project.instructions or "",
            memories=memories,
            thread_instructions=thread.system_prompt or "",
            tool_names=[t["function"]["name"] for t in tools] if tools else None,
        )

        await self.emit(
            "run_start",
            {
                "model": resolved.model,
                "provider": resolved.provider_name,
                "mode": mode,
                "sandbox": backend,
                "tools": len(tools),
            },
        )

        for step in range(settings.MAX_AGENT_STEPS):
            self._check_cancel()
            # Long runs must not get reaped mid-turn: every step counts as use.
            sandboxes.touch(self.thread_id)

            for injected in runs.take_steering(self.thread_id):
                history.append({"role": "user", "content": f"[User, mid-run] {injected}"})
                await self.emit("message_start", {"id": new_id("msg"), "role": "user", "content": injected})

            if needs_compaction(history):
                history, summary = await compact(history, client=client, model=resolved.model)
                await self.emit("compacted", {"summary": summary, "tokens": estimate_tokens(history)})

            messages = [{"role": "system", "content": system_prompt}, *history]
            assistant_id = new_id("msg")
            await self.emit("message_start", {"id": assistant_id, "role": "assistant", "step": step})

            text_parts: list[str] = []
            reasoning_parts: list[str] = []
            tool_calls: list[ToolCall] = []
            finish_reason = ""

            step_started = time.perf_counter()
            async def _thinking_heartbeat(
                started_at=step_started, current_id=assistant_id, current_step=step
            ):
                try:
                    while True:
                        await asyncio.sleep(1.2)
                        elapsed = round(time.perf_counter() - started_at, 1)
                        await self.emit(
                            "thinking_progress",
                            {
                                "id": current_id,
                                "step": current_step,
                                "elapsed_s": elapsed,
                                "status": "thinking",
                            },
                        )
                except asyncio.CancelledError:
                    pass

            think_task = asyncio.create_task(_thinking_heartbeat())
            try:
                async for delta in client.stream(
                    model=resolved.model, messages=messages, tools=tools or None, temperature=0.3
                ):
                    self._check_cancel()
                    if delta.kind == "text":
                        text_parts.append(delta.text)
                        await self.emit("text_delta", {"id": assistant_id, "text": delta.text})
                    elif delta.kind == "reasoning":
                        reasoning_parts.append(delta.text)
                        await self.emit("reasoning_delta", {"id": assistant_id, "text": delta.text})
                    elif delta.kind == "tool_call" and delta.tool_call:
                        tool_calls.append(delta.tool_call)
                    elif delta.kind == "usage" and delta.usage:
                        self.usage["prompt_tokens"] += delta.usage.prompt_tokens
                        self.usage["completion_tokens"] += delta.usage.completion_tokens
                        await self.emit("usage", {**self.usage})
                    elif delta.kind == "stop":
                        finish_reason = delta.finish_reason
            finally:
                think_task.cancel()

            content = "".join(text_parts)
            reasoning = "".join(reasoning_parts)
            assistant_raw: dict[str, Any] = {"role": "assistant", "content": content}
            if tool_calls:
                assistant_raw["tool_calls"] = [tc.to_openai() for tc in tool_calls]
            history.append(assistant_raw)

            async with SessionLocal() as db:
                await self._save_message(
                    db,
                    role="assistant",
                    content=content,
                    reasoning=reasoning,
                    raw=assistant_raw,
                    message_id=assistant_id,
                    meta={
                        "model": resolved.model,
                        "provider": resolved.provider_name,
                        "finish_reason": finish_reason,
                        "step": step,
                    },
                )

            await self.emit(
                "message_end",
                {"id": assistant_id, "content": content, "tool_calls": len(tool_calls)},
            )

            if not tool_calls:
                self._last_tool_fp = None
                self._repeat_count = 0
                break

            # Same exact tool call(s) 3 steps in a row = the model is looped,
            # not progressing (looks "stuck" to the user). Stop visibly instead
            # of burning the 80-step budget on repeats.
            repeat_msg = self._check_repeat(tool_calls)
            if repeat_msg is not None:
                await self.emit("error", {"message": repeat_msg, "kind": "repeat"})
                break

            results = await self._execute_tool_calls(
                tool_calls, sandbox, permission_mode, assistant_id
            )
            history.extend(results)
            checkpoint = await self._browser_checkpoint(tool_calls, results)
            if checkpoint:
                history.append({"role": "user", "content": checkpoint})
        else:
            await self.emit(
                "error",
                {"message": f"Hit the {settings.MAX_AGENT_STEPS}-step limit.", "kind": "limit"},
            )

        await self._finalize(resolved)

    # ---- tool execution --------------------------------------------------

    def _make_ctx(self, sandbox, tool_call_id: str) -> ToolContext:
        return ToolContext(
            thread_id=self.thread_id,
            project_id=self.project.id,
            workspace=self.project.workspace_path,
            sandbox=sandbox,
            emit=lambda type_, payload: self.emit(type_, payload),
            tool_call_id=tool_call_id,
            depth=self.depth,
            state=self.state,
        )

    async def _execute_tool_calls(
        self, tool_calls: list[ToolCall], sandbox, permission_mode: str, message_id: str
    ) -> list[dict[str, Any]]:
        parallelisable = [
            tc
            for tc in tool_calls
            if (tool := registry.get(tc.name)) and tool.group in PARALLEL_SAFE_GROUPS and not tool.mutating
        ]
        if len(tool_calls) > 1 and len(parallelisable) == len(tool_calls):
            outputs = await asyncio.gather(
                *(self._execute_one(tc, sandbox, permission_mode, message_id) for tc in tool_calls)
            )
            return list(outputs)

        results: list[dict[str, Any]] = []
        for call in tool_calls:
            self._check_cancel()
            results.append(await self._execute_one(call, sandbox, permission_mode, message_id))
        return results

    async def _browser_checkpoint(
        self, tool_calls: list[ToolCall], results: list[dict[str, Any]]
    ) -> str | None:
        """Inspect browser state after actions and feed bounded recovery context back to the model."""
        browser_calls = [tc for tc in tool_calls if tc.name.startswith("browser_")]
        if not browser_calls or all(tc.name in {"browser_inspect", "browser_screenshot"} for tc in browser_calls):
            return None
        if self._browser_recovery_count >= 3:
            return "Browser recovery budget exhausted. Do not repeat the same action; explain the current blocker."
        self._browser_recovery_count += 1
        try:
            from app.browser import browsers

            session = await browsers.peek(self.thread_id)
            if not session:
                return "Browser checkpoint unavailable: no active browser session."
            state = await session.inspect(max_chars=8000)
            failed = any("failed" in str(result.get("content", "")).lower() for result in results)
            await self.emit(
                "browser_recovery",
                {
                    "attempt": self._browser_recovery_count,
                    "failed_action": failed,
                    "url": state.get("url", ""),
                    "title": state.get("title", ""),
                    "text_preview": truncate(state.get("text", ""), 800),
                },
            )
            return (
                f"Browser checkpoint {self._browser_recovery_count}/3: current URL={state.get('url', '')!r}, "
                f"title={state.get('title', '')!r}. The page was re-inspected. Verify the intended state now; "
                "if the previous action failed, choose a different selector or strategy."
            )
        except Exception as exc:
            return f"Browser checkpoint failed: {exc}. Re-inspect before retrying."

    async def _execute_one(
        self, call: ToolCall, sandbox, permission_mode: str, message_id: str
    ) -> dict[str, Any]:
        tool = registry.get(call.name)
        await self.emit(
            "tool_call",
            {
                "id": call.id,
                "message_id": message_id,
                "name": call.name,
                "arguments": call.arguments,
                "group": tool.group if tool else "unknown",
            },
        )

        started = time.perf_counter()
        status = "ok"
        result: ToolResult = ToolResult(content="")

        if tool is None:
            result = ToolResult.error(
                f"unknown tool `{call.name}`. Available: {', '.join(registry.names()[:40])}"
            )
            status = "error"
        else:
            reason = permissions.needs_approval(self.thread_id, permission_mode, tool, call.arguments)

            # --- Pre-Tool Hook Interception ---
            ctx = self._make_ctx(sandbox, call.id)
            try:
                from app.agent.hooks import hooks
                hook_error = await hooks.pre_tool_hook(tool, ctx, call.arguments)
                if hook_error:
                    reason = None # Override execution completely
                    result = ToolResult.error(hook_error)
                    status = "error"
            except Exception:
                pass

            if status != "error" and reason:
                request_id = new_id("perm")
                await self.emit(
                    "permission_request",
                    {
                        "request_id": request_id,
                        "tool_call_id": call.id,
                        "tool": call.name,
                        "arguments": call.arguments,
                        "reason": reason,
                    },
                )
                decision = await permissions.ask(
                    self.thread_id, request_id, call.name, call.arguments, reason
                )
                if decision == "deny":
                    result = ToolResult(
                        content="The user denied this action. Do not retry it; take a different approach or ask them what they want instead.",
                        is_error=True,
                    )
                    status = "denied"
                    await self._record_tool_call(call, result, status, started, message_id)
                    await self.emit(
                        "tool_result",
                        {"id": call.id, "name": call.name, "status": status, "content": result.content},
                    )
                    return {"role": "tool", "tool_call_id": call.id, "content": result.content}

            ctx = self._make_ctx(sandbox, call.id)
            if status != "error":
                async def _progress_heartbeat():
                    try:
                        while True:
                            await asyncio.sleep(1.2)
                            elapsed = round(time.perf_counter() - started, 1)
                            await self.emit(
                                "tool_progress",
                                {
                                    "id": call.id,
                                    "name": call.name,
                                    "elapsed_s": elapsed,
                                    "status": "executing",
                                },
                            )
                    except asyncio.CancelledError:
                        pass

                progress_task = asyncio.create_task(_progress_heartbeat())
                try:
                    result = await tool.invoke(ctx, call.arguments)
                    status = "error" if result.is_error else "ok"

                    # --- Post-Tool Hook Execution ---
                    try:
                        from app.agent.hooks import hooks
                        result = await hooks.post_tool_hook(tool, ctx, result)
                    except Exception:
                        pass
                except Interrupted:
                    raise
                except Exception as exc:
                    log.exception("tool %s blew up", call.name)
                    result = ToolResult.error(f"{type(exc).__name__}: {exc}")
                    status = "error"
                finally:
                    progress_task.cancel()

        if call.name == "todo_write":
            await self._persist_todos()

        await self._record_tool_call(call, result, status, started, message_id)
        await self.emit(
            "tool_result",
            {
                "id": call.id,
                "name": call.name,
                "status": status,
                "content": truncate(result.content, 4000),
                "display": result.display,
                "duration_ms": int((time.perf_counter() - started) * 1000),
            },
        )
        return {
            "role": "tool",
            "tool_call_id": call.id,
            "content": truncate(result.content, TOOL_RESULT_LIMIT),
        }

    async def _record_tool_call(
        self, call: ToolCall, result: ToolResult, status: str, started: float, message_id: str
    ) -> None:
        async with SessionLocal() as db:
            db.add(
                ToolCallRecord(
                    call_id=call.id,
                    thread_id=self.thread_id,
                    message_id=message_id,
                    name=call.name,
                    arguments=call.arguments,
                    result=truncate(result.content, 60_000),
                    display=result.display or {},
                    status=status,
                    duration_ms=int((time.perf_counter() - started) * 1000),
                )
            )
            await db.commit()

    async def _persist_todos(self) -> None:
        async with SessionLocal() as db:
            row = await db.get(Thread, self.thread_id)
            if row:
                row.todos = self.state.get("todos", [])
                await db.commit()

    # ---- finalisation ----------------------------------------------------

    async def _finalize(self, resolved) -> None:
        async with SessionLocal() as db:
            thread = await db.get(Thread, self.thread_id)
            if thread is None:
                return
            thread.status = "idle"
            thread.last_message_at = func.now()
            usage = dict(thread.token_usage or {})
            usage["prompt_tokens"] = usage.get("prompt_tokens", 0) + self.usage["prompt_tokens"]
            usage["completion_tokens"] = usage.get("completion_tokens", 0) + self.usage["completion_tokens"]
            from app.core.cost import calculate_turn_cost

            cost_usd = calculate_turn_cost(
                model=resolved.model,
                prompt_tokens=self.usage["prompt_tokens"],
                completion_tokens=self.usage["completion_tokens"],
            )
            usage["cost_usd"] = round(usage.get("cost_usd", 0.0) + cost_usd, 6)
            thread.token_usage = usage
            db.add(
                UsageStat(
                    thread_id=self.thread_id,
                    model=resolved.model,
                    prompt_tokens=self.usage["prompt_tokens"],
                    completion_tokens=self.usage["completion_tokens"],
                )
            )
            needs_title = thread.title in ("", "New chat")
            await db.commit()

        if needs_title:
            await self._generate_title(resolved)

    async def _generate_title(self, resolved) -> None:
        async with SessionLocal() as db:
            rows = (
                await db.execute(
                    select(Message)
                    .where(Message.thread_id == self.thread_id, Message.role.in_(("user", "assistant")))
                    .order_by(Message.position)
                    .limit(4)
                )
            ).scalars().all()
        excerpt = "\n\n".join(f"{r.role}: {truncate(r.content, 800)}" for r in rows if r.content)
        if not excerpt.strip():
            return
        try:
            completion = await resolved.client().complete(
                model=resolved.model,
                messages=[
                    {"role": "system", "content": TITLE_PROMPT},
                    {"role": "user", "content": excerpt},
                ],
                temperature=0.3,
                max_tokens=40,
            )
            title = completion.content.strip().strip('"').splitlines()[0][:120]
        except Exception:
            return
        if not title:
            return
        async with SessionLocal() as db:
            thread = await db.get(Thread, self.thread_id)
            if thread:
                thread.title = title
                await db.commit()
        await self.emit("title", {"title": title})


# ---------------------------------------------------------------------------
# Subagents
# ---------------------------------------------------------------------------


async def run_subagent(
    *,
    parent: ToolContext,
    system_extra: str,
    prompt: str,
    max_steps: int,
    label: str,
) -> str:
    """Run a nested loop that shares the sandbox but starts with an empty context."""
    async with SessionLocal() as db:
        thread = await db.get(Thread, parent.thread_id)
        project = await db.get(Project, parent.project_id)
        resolved = await resolve_model(db, provider_id=thread.provider_id, model=thread.model)

    client = resolved.client()
    tools = registry.schemas(exclude={"task"})
    system = build_system_prompt(
        mode="agent",
        workspace=parent.sandbox.workdir,
        sandbox_backend=await sandboxes.backend(),
        project_name=project.name,
        project_instructions=project.instructions or "",
    ) + f"\n\n## Your assignment\n\n{system_extra}\n\nReport back in your final message; nobody sees your intermediate steps."

    history: list[dict[str, Any]] = [{"role": "user", "content": prompt}]
    final_text = ""

    for _ in range(max_steps):
        completion = await client.complete(
            model=resolved.model,
            messages=[{"role": "system", "content": system}, *history],
            tools=tools,
            temperature=0.2,
        )
        history.append(completion.to_openai_message())
        if completion.content:
            final_text = completion.content
        if not completion.tool_calls:
            break

        for call in completion.tool_calls:
            tool = registry.get(call.name)
            await parent.emit(
                "subagent_step",
                {"tool_call_id": parent.tool_call_id, "label": label, "tool": call.name},
            )
            if tool is None:
                output = f"ERROR: unknown tool `{call.name}`"
            else:
                # Subagents get the same approval gate as the main loop —
                # a poisoned subagent prompt must never auto-run gated tools.
                reason = permissions.needs_approval(
                    parent.thread_id, thread.permission_mode or "auto",
                    tool, call.arguments,
                )
                if reason:
                    request_id = new_id("perm")
                    await parent.emit(
                        "permission_request",
                        {
                            "request_id": request_id,
                            "tool_call_id": call.id,
                            "tool": call.name,
                            "arguments": call.arguments,
                            "reason": f"[subagent {label}] {reason}",
                        },
                    )
                    sub_decision = await permissions.ask(
                        parent.thread_id, request_id, call.name, call.arguments, reason
                    )
                    if sub_decision == "deny":
                        output = (
                            "The user denied this action. Do not retry it; "
                            "take a different approach or ask them what they want instead."
                        )
                        history.append(
                            {"role": "tool", "tool_call_id": call.id, "content": truncate(output, TOOL_RESULT_LIMIT)}
                        )
                        continue
                child_ctx = ToolContext(
                    thread_id=parent.thread_id,
                    project_id=parent.project_id,
                    workspace=parent.workspace,
                    sandbox=parent.sandbox,
                    emit=parent.emit,
                    tool_call_id=call.id,
                    depth=parent.depth + 1,
                    state=parent.state,
                )
                try:
                    result = await tool.invoke(child_ctx, call.arguments)
                    output = result.content
                except Exception as exc:
                    output = f"ERROR: {type(exc).__name__}: {exc}"
            history.append(
                {"role": "tool", "tool_call_id": call.id, "content": truncate(output, TOOL_RESULT_LIMIT)}
            )

    return final_text or "(subagent produced no final report)"
