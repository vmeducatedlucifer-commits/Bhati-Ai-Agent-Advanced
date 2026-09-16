"""Telegram Bot Integration for Rawal AI.

Allows authorized users to interact with Rawal AI directly via Telegram:
- Two-way file sharing (documents, code files, screenshots)
- Model switching (/model)
- Workspace execution, project & thread management
- Auto-mapped Telegram command menu
- High security: Strict allowlist validation per message
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any

import httpx

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger("app.telegram")

BOT_COMMANDS = [
    {"command": "start", "description": "Welcome & agent capabilities"},
    {"command": "new", "description": "Create a new conversation session"},
    {"command": "model", "description": "View or switch active AI model"},
    {"command": "projects", "description": "List & select active project"},
    {"command": "files", "description": "Browse files in workspace"},
    {"command": "getfile", "description": "Download a workspace file to Telegram"},
    {"command": "exec", "description": "Run shell command in sandbox"},
    {"command": "status", "description": "Check cloud database & server health"},
    {"command": "clear", "description": "Clear conversation history"},
    {"command": "help", "description": "Show help and command list"},
]


class TelegramBot:
    def __init__(self) -> None:
        self.token = ""
        self.allowed_ids: set[str] = set()
        self.enabled = False
        self.bot_username = ""
        self._offset = 0
        self._task: asyncio.Task | None = None
        self._http: httpx.AsyncClient | None = None
        self._active_thread_per_user: dict[str, str] = {}
        self._active_project_per_user: dict[str, str] = {}

    def _parse_allowed_ids(self) -> set[str]:
        raw = settings.TELEGRAM_ALLOWED_USER_IDS.strip()
        if not raw or raw == "*":
            return {"*"}
        return {x.strip().lower() for x in raw.split(",") if x.strip()}

    async def init(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
        if self._http:
            await self._http.aclose()

        self.token = settings.TELEGRAM_BOT_TOKEN.strip()
        if not self.token:
            # Check database settings
            try:
                from app.db.models import Setting
                from app.db.session import SessionLocal
                async with SessionLocal() as db:
                    setting = await db.get(Setting, "telegram_config")
                    if setting and isinstance(setting.value, dict):
                        self.token = setting.value.get("bot_token", "").strip()
                        if not settings.TELEGRAM_ALLOWED_USER_IDS:
                            settings.TELEGRAM_ALLOWED_USER_IDS = setting.value.get("allowed_user_ids", "")
            except Exception as e:
                log.warning("Could not read telegram_config from DB: %s", e)

        if not self.token:
            log.info("Telegram bot disabled (no TELEGRAM_BOT_TOKEN provided).")
            self.enabled = False
            self.bot_username = ""
            return

        self.allowed_ids = self._parse_allowed_ids()
        self._http = httpx.AsyncClient(timeout=60)
        self.enabled = True

        try:
            r = await self._http.get(f"https://api.telegram.org/bot{self.token}/getMe")
            data = r.json()
            if data.get("ok"):
                self.bot_username = data.get("result", {}).get("username", "bot")
                log.info("Telegram Bot @%s initialized. Allowed users: %s", self.bot_username, self.allowed_ids or "ALL")

                # Automatically map Telegram command menu
                await self._register_commands()

                self._task = asyncio.create_task(self._polling_loop())
            else:
                log.error("Telegram Bot initialization failed: %s", data)
                self.enabled = False
                self.bot_username = ""
        except Exception as exc:
            log.error("Failed to connect to Telegram API: %s", exc)
            self.enabled = False
            self.bot_username = ""

    async def _register_commands(self) -> None:
        """Register the bot commands with Telegram so they appear in the auto-complete menu."""
        if not self._http or not self.token:
            return
        try:
            url = f"https://api.telegram.org/bot{self.token}/setMyCommands"
            await self._http.post(url, json={"commands": BOT_COMMANDS})
            log.info("Registered %d Telegram bot menu commands.", len(BOT_COMMANDS))
        except Exception as exc:
            log.warning("Failed to register Telegram commands: %s", exc)

    async def shutdown(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        if self._http:
            await self._http.aclose()
        log.info("Telegram Bot stopped.")

    def _is_authorized(self, user_id: int | str, username: str = "") -> bool:
        if "*" in self.allowed_ids:
            return True
        uid_str = str(user_id).strip().lower()
        uname_str = (username or "").strip().lower().lstrip("@")
        return uid_str in self.allowed_ids or (f"@{uname_str}" in self.allowed_ids or uname_str in self.allowed_ids)

    async def send_message(self, chat_id: int | str, text: str, parse_mode: str = "Markdown") -> None:
        if not self._http or not self.token:
            return
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"

        chunks = [text[i:i + 4000] for i in range(0, len(text), 4000)] if len(text) > 4000 else [text]
        for chunk in chunks:
            try:
                payload = {"chat_id": chat_id, "text": chunk, "parse_mode": parse_mode}
                r = await self._http.post(url, json=payload)
                if not r.json().get("ok"):
                    payload["parse_mode"] = ""
                    await self._http.post(url, json=payload)
            except Exception as exc:
                log.warning("Telegram send_message failed: %s", exc)

    async def send_document(self, chat_id: int | str, file_path: str, caption: str = "") -> bool:
        """Send a local file from the workspace to the user on Telegram."""
        if not self._http or not self.token or not os.path.isfile(file_path):
            return False
        url = f"https://api.telegram.org/bot{self.token}/sendDocument"
        filename = os.path.basename(file_path)
        try:
            with open(file_path, "rb") as f:
                files = {"document": (filename, f)}
                data = {"chat_id": chat_id, "caption": caption}
                r = await self._http.post(url, data=data, files=files)
                return bool(r.json().get("ok"))
        except Exception as exc:
            log.warning("Telegram send_document failed: %s", exc)
            return False

    async def _download_telegram_file(self, file_id: str, dest_dir: str, file_name: str) -> str | None:
        """Download a document sent by user on Telegram into workspace uploads."""
        if not self._http or not self.token:
            return None
        try:
            # 1. Get file path from Telegram
            r = await self._http.get(f"https://api.telegram.org/bot{self.token}/getFile", params={"file_id": file_id})
            res = r.json()
            if not res.get("ok"):
                return None
            remote_path = res["result"]["file_path"]

            # 2. Download the actual content
            download_url = f"https://api.telegram.org/file/bot{self.token}/{remote_path}"
            r_file = await self._http.get(download_url)
            if r_file.status_code != 200:
                return None

            os.makedirs(dest_dir, exist_ok=True)
            local_path = os.path.join(dest_dir, file_name)
            with open(local_path, "wb") as f:
                f.write(r_file.content)
            return local_path
        except Exception as exc:
            log.error("Failed downloading telegram file %s: %s", file_id, exc)
            return None

    async def _handle_command(self, chat_id: int | str, user_id: int | str, text: str) -> None:
        parts = text.strip().split(maxsplit=1)
        cmd = parts[0].lower().split("@")[0]
        args = parts[1].strip() if len(parts) > 1 else ""

        from sqlalchemy import select

        from app.db.models import Project, Provider, Thread
        from app.db.session import SessionLocal

        if cmd in ("/start", "/help"):
            help_text = (
                "🤖 *Rawal AI — Full Capabilities Menu*\n\n"
                "*Commands:*\n"
                "• `/new [title]` — Start a new isolated chat session\n"
                "• `/model [name]` — Switch AI model (e.g. `gpt-4o`, `claude-3-5-sonnet`)\n"
                "• `/projects` — List & select projects\n"
                "• `/files` — List files in current project\n"
                "• `/getfile <path>` — Send workspace file directly to this chat\n"
                "• `/exec <bash>` — Execute command in Linux sandbox\n"
                "• `/status` — Check cloud storage & system health\n"
                "• `/clear` — Clear thread conversation history\n\n"
                "📎 *File Sharing:* Send any code file, document, or image to upload it into the workspace.\n"
                "💬 Or simply send a text prompt to build or fix code!"
            )
            await self.send_message(chat_id, help_text)

        elif cmd == "/status":
            from app.db.mongo import mongo_manager
            from app.sandbox.manager import sandboxes
            from app.storage.gdrive import gdrive_manager

            mongo_st = "🟢 Active" if mongo_manager.enabled else "⚪ Disabled"
            gdrive_st = "🟢 Active" if gdrive_manager.enabled else "⚪ Disabled"
            backend_st = await sandboxes.backend()

            tid = self._active_thread_per_user.get(str(user_id), "None")
            status_msg = (
                "📊 *Rawal AI System Status*\n\n"
                f"• *App Version:* v2.0.0\n"
                f"• *Active Session ID:* `{tid}`\n"
                f"• *MongoDB Persistence:* {mongo_st}\n"
                f"• *Google Drive Storage:* {gdrive_st}\n"
                f"• *Sandbox Runtime:* `{backend_st}`\n"
                f"• *Default Model:* `{settings.DEFAULT_LLM_MODEL}`\n"
            )
            await self.send_message(chat_id, status_msg)

        elif cmd == "/model":
            async with SessionLocal() as db:
                tid = self._active_thread_per_user.get(str(user_id))
                thread = await db.get(Thread, tid) if tid else None

                if not args:
                    # List models
                    providers = (await db.execute(select(Provider).where(Provider.enabled.is_(True)))).scalars().all()
                    available = []
                    for p in providers:
                        available.extend(p.models or ([p.default_model] if p.default_model else []))
                    if settings.DEFAULT_LLM_MODEL and settings.DEFAULT_LLM_MODEL not in available:
                        available.insert(0, settings.DEFAULT_LLM_MODEL)

                    current_model = thread.model if thread else settings.DEFAULT_LLM_MODEL
                    msg = f"🧠 *Active Model:* `{current_model}`\n\n*Available Models:*\n"
                    for m in available[:15]:
                        msg += f"• `{m}`\n"
                    msg += "\nTo switch, use: `/model <model_name>`"
                    await self.send_message(chat_id, msg)
                else:
                    new_model = args.strip()
                    if thread:
                        thread.model = new_model
                        await db.commit()
                        await self.send_message(chat_id, f"✅ Switched session model to: `{new_model}`")
                    else:
                        await self.send_message(chat_id, f"✅ Model set to: `{new_model}` (will be used for next thread).")

        elif cmd == "/projects":
            async with SessionLocal() as db:
                projects = (await db.execute(select(Project).where(Project.archived.is_(False)))).scalars().all()
                if not projects:
                    await self.send_message(chat_id, "No projects found. Send `/new` to create one.")
                    return

                msg = "📁 *Your Projects:*\n\n"
                for p in projects:
                    msg += f"• *{p.name}* (ID: `{p.id}`)\n"
                await self.send_message(chat_id, msg)

        elif cmd == "/new":
            title = args or "Telegram Chat"
            async with SessionLocal() as db:
                projects = (await db.execute(select(Project).where(Project.archived.is_(False)))).scalars().all()
                if not projects:
                    from app.core.utils import new_id
                    pid = new_id("prj")
                    ws = os.path.join(settings.WORKSPACE_ROOT, f"default-{pid[-6:]}")
                    os.makedirs(ws, exist_ok=True)
                    project = Project(id=pid, name="Default Project", slug="default", workspace_path=ws)
                    db.add(project)
                    await db.commit()
                else:
                    project = projects[0]

                thread = Thread(
                    project_id=project.id,
                    title=f"[TG] {title}",
                    mode="agent",
                    model=settings.DEFAULT_LLM_MODEL,
                    source="telegram",
                )
                db.add(thread)
                await db.commit()

                self._active_thread_per_user[str(user_id)] = thread.id
                self._active_project_per_user[str(user_id)] = project.id
                await self.send_message(chat_id, f"✨ Started new Telegram session: *{title}*\nProject: `{project.name}`")

        elif cmd == "/clear":
            async with SessionLocal() as db:
                tid = self._active_thread_per_user.get(str(user_id))
                if tid:
                    thread = await db.get(Thread, tid)
                    if thread:
                        for m in list(thread.messages):
                            await db.delete(m)
                        thread.todos = []
                        await db.commit()
                        await self.send_message(chat_id, "🧹 Conversation history cleared.")
                        return
            await self.send_message(chat_id, "No active session to clear.")

        elif cmd == "/files":
            from app.sandbox.manager import sandboxes
            tid = self._active_thread_per_user.get(str(user_id), "telegram-sandbox")
            pid = self._active_project_per_user.get(str(user_id))
            ws_path = settings.WORKSPACE_ROOT

            async with SessionLocal() as db:
                if pid:
                    p = await db.get(Project, pid)
                    if p:
                        ws_path = p.workspace_path

            box = await sandboxes.get(tid, ws_path)
            entries = await box.list_dir(args)
            if not entries:
                await self.send_message(chat_id, f"📂 `{args or '.'}` is empty.")
                return

            lines = [f"📁 Files in `{args or '.'}`:"]
            for e in entries[:30]:
                icon = "📁" if e.is_dir else "📄"
                lines.append(f"{icon} `{e.name}`" + (f" ({e.size}b)" if not e.is_dir else ""))
            lines.append("\nTo download a file, send `/getfile <path>`")
            await self.send_message(chat_id, "\n".join(lines))

        elif cmd == "/getfile":
            if not args:
                await self.send_message(chat_id, "Usage: `/getfile <filename>`")
                return

            pid = self._active_project_per_user.get(str(user_id))
            ws_path = settings.WORKSPACE_ROOT
            async with SessionLocal() as db:
                if pid:
                    p = await db.get(Project, pid)
                    if p:
                        ws_path = p.workspace_path

            ws_root = Path(ws_path).resolve()
            target = (ws_root / args).resolve()
            # Path traversal prevention: ensure target is strictly inside ws_root
            if ws_root not in target.parents and target != ws_root:
                await self.send_message(chat_id, "❌ Error: Access denied. Path escapes workspace.")
                return

            if not target.is_file():
                await self.send_message(chat_id, f"❌ File not found: `{args}`")
                return

            await self.send_document(chat_id, str(target), caption=f"📄 {target.name}")

        elif cmd == "/exec":
            if not args:
                await self.send_message(chat_id, "Usage: `/exec <bash command>`")
                return

            from app.tools.shell import _is_banned
            if banned := _is_banned(args):
                await self.send_message(chat_id, f"❌ Refusing to run destructive command containing `{banned}`.")
                return

            from app.sandbox.manager import sandboxes
            tid = self._active_thread_per_user.get(str(user_id), "telegram-sandbox")
            pid = self._active_project_per_user.get(str(user_id))
            ws_path = settings.WORKSPACE_ROOT

            async with SessionLocal() as db:
                if pid:
                    p = await db.get(Project, pid)
                    if p:
                        ws_path = p.workspace_path

            box = await sandboxes.get(tid, ws_path)
            res = await box.exec(args, timeout=60)

            output = (res.stdout + "\n" + res.stderr).strip() or "(No output)"
            await self.send_message(chat_id, f"💻 *Exit Code: {res.exit_code}*\n```\n{output[:3500]}\n```")

        else:
            await self._handle_agent_message(chat_id, user_id, text)

    async def _handle_agent_message(
        self,
        chat_id: int | str,
        user_id: int | str,
        text: str,
        attachments: list[dict[str, Any]] | None = None,
    ) -> None:
        from sqlalchemy import select

        from app.agent.loop import AgentRunner
        from app.db.models import Artifact, Project, Thread
        from app.db.session import SessionLocal

        async with SessionLocal() as db:
            tid = self._active_thread_per_user.get(str(user_id))
            pid = self._active_project_per_user.get(str(user_id))

            thread = await db.get(Thread, tid) if tid else None
            project = await db.get(Project, pid) if pid else None

            if not project:
                projects = (await db.execute(select(Project).where(Project.archived.is_(False)))).scalars().all()
                if not projects:
                    from app.core.utils import new_id
                    pid = new_id("prj")
                    ws = os.path.join(settings.WORKSPACE_ROOT, f"default-{pid[-6:]}")
                    os.makedirs(ws, exist_ok=True)
                    project = Project(id=pid, name="Default Project", slug="default", workspace_path=ws)
                    db.add(project)
                    await db.commit()
                else:
                    project = projects[0]

            if not thread:
                threads = (
                    await db.execute(
                        select(Thread).where(Thread.project_id == project.id, Thread.source == "telegram")
                    )
                ).scalars().all()
                if not threads:
                    thread = Thread(
                        project_id=project.id,
                        title="Telegram Session",
                        mode="agent",
                        model=settings.DEFAULT_LLM_MODEL,
                        source="telegram",
                    )
                    db.add(thread)
                    await db.commit()
                else:
                    thread = threads[0]

            self._active_thread_per_user[str(user_id)] = thread.id
            self._active_project_per_user[str(user_id)] = project.id

        await self.send_message(chat_id, "⏳ *Rawal AI is thinking & executing tools...*")

        # Run agent loop
        try:
            runner = AgentRunner(thread=thread, project=project)
            await runner.run(text, attachments=attachments or [])

            # Check for generated artifacts to send to user as files
            async with SessionLocal() as db:
                from app.db.models import Message
                msg_row = (
                    await db.execute(
                        select(Message)
                        .where(Message.thread_id == thread.id, Message.role == "assistant")
                        .order_by(Message.position.desc())
                    )
                ).scalars().first()

                artifacts = (
                    await db.execute(
                        select(Artifact).where(Artifact.thread_id == thread.id).order_by(Artifact.created_at.desc())
                    )
                ).scalars().all()

                if msg_row and msg_row.content:
                    await self.send_message(chat_id, f"🤖 *Rawal AI:*\n\n{msg_row.content}")
                else:
                    await self.send_message(chat_id, "✅ Task completed.")

                # If any artifact was created during this turn, send file to Telegram!
                for art in artifacts[:2]:
                    if art.path:
                        local_art_path = os.path.join(project.workspace_path, art.path)
                        if os.path.isfile(local_art_path):
                            await self.send_document(chat_id, local_art_path, caption=f"📦 Generated: {art.title}")

        except Exception as exc:
            log.exception("Telegram Agent Execution error: %s", exc)
            await self.send_message(chat_id, f"❌ Error during execution: `{exc}`")

    async def _polling_loop(self) -> None:
        log.info("Telegram polling loop running.")
        while self.enabled:
            try:
                url = f"https://api.telegram.org/bot{self.token}/getUpdates"
                params = {"offset": self._offset, "timeout": 30}
                r = await self._http.get(url, params=params)
                data = r.json()

                if not data.get("ok"):
                    await asyncio.sleep(2)
                    continue

                for update in data.get("result", []):
                    self._offset = update["update_id"] + 1
                    msg = update.get("message")
                    if not msg:
                        continue

                    chat_id = msg["chat"]["id"]
                    user = msg.get("from", {})
                    user_id = user.get("id", "")
                    username = user.get("username", "")

                    # Security Verification
                    if not self._is_authorized(user_id, username):
                        log.warning("Unauthorized Telegram access attempt from ID: %s (@%s)", user_id, username)
                        await self.send_message(
                            chat_id,
                            f"⛔ *Access Denied*\nYour Telegram User ID is `{user_id}`.\n"
                            "Ask the administrator to add this ID to `TELEGRAM_ALLOWED_USER_IDS`."
                        )
                        continue

                    # Handle Document / File sent from user
                    if "document" in msg or "photo" in msg:
                        file_id = ""
                        file_name = "upload.bin"
                        if "document" in msg:
                            file_id = msg["document"]["file_id"]
                            file_name = msg["document"].get("file_name", "document.txt")
                        elif "photo" in msg:
                            file_id = msg["photo"][-1]["file_id"]
                            file_name = f"photo_{file_id[-6:]}.jpg"

                        caption = msg.get("caption", "").strip() or f"Analyze this uploaded file: {file_name}"

                        # Determine destination directory
                        pid = self._active_project_per_user.get(str(user_id))
                        ws_path = settings.WORKSPACE_ROOT
                        from app.db.models import Project
                        from app.db.session import SessionLocal
                        async with SessionLocal() as db:
                            if pid:
                                p = await db.get(Project, pid)
                                if p:
                                    ws_path = p.workspace_path

                        dest_dir = os.path.join(ws_path, "uploads")
                        saved_path = await self._download_telegram_file(file_id, dest_dir, file_name)
                        if saved_path:
                            rel_path = os.path.relpath(saved_path, ws_path)
                            await self.send_message(chat_id, f"📥 Received and saved file to `{rel_path}`.")
                            attachments = [{"name": file_name, "path": rel_path, "size": os.path.getsize(saved_path)}]
                            asyncio.create_task(self._handle_agent_message(chat_id, user_id, caption, attachments=attachments))
                        else:
                            await self.send_message(chat_id, "❌ Failed to download file from Telegram.")
                        continue

                    # Handle Text Message
                    text = msg.get("text", "").strip()
                    if text:
                        if text.startswith("/"):
                            asyncio.create_task(self._handle_command(chat_id, user_id, text))
                        else:
                            asyncio.create_task(self._handle_agent_message(chat_id, user_id, text))

            except asyncio.CancelledError:
                break
            except Exception as exc:
                log.error("Telegram polling error: %s", exc)
                await asyncio.sleep(3)


telegram_bot = TelegramBot()
