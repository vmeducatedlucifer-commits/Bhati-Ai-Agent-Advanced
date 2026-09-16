"""Persistence model.

Projects own workspaces. Threads (chat sessions) live in a project. Every assistant
turn is stored as a Message plus a flat list of Events, so a reload replays exactly
what the browser saw live.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.utils import new_id
from app.db.base import Base, TimestampMixin


class Project(Base, TimestampMixin):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("prj"))
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    slug: Mapped[str] = mapped_column(String(200), default="")
    workspace_path: Mapped[str] = mapped_column(String(600), nullable=False)
    instructions: Mapped[str] = mapped_column(Text, default="")
    icon: Mapped[str] = mapped_column(String(40), default="folder")
    color: Mapped[str] = mapped_column(String(20), default="orange")
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    gdrive_file_id: Mapped[str] = mapped_column(String(200), default="")
    github_repo: Mapped[str] = mapped_column(String(300), default="")

    threads: Mapped[list[Thread]] = relationship(
        back_populates="project", cascade="all, delete-orphan", lazy="selectin"
    )


class Thread(Base, TimestampMixin):
    __tablename__ = "threads"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("thr"))
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(300), default="New chat")
    model: Mapped[str] = mapped_column(String(160), default="")
    provider_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    mode: Mapped[str] = mapped_column(String(20), default="agent")  # agent | chat | plan
    system_prompt: Mapped[str] = mapped_column(Text, default="")
    # Uncensored default: auto (no permission prompts)
    permission_mode: Mapped[str] = mapped_column(String(20), default="auto")  # auto | ask | plan | bypass | uncensored
    status: Mapped[str] = mapped_column(String(20), default="idle")  # idle | running | error
    sandbox_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    pinned: Mapped[bool] = mapped_column(Boolean, default=False)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    source: Mapped[str] = mapped_column(String(20), default="web")  # web | telegram
    todos: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    token_usage: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    project: Mapped[Project] = relationship(back_populates="threads")
    messages: Mapped[list[Message]] = relationship(
        back_populates="thread",
        cascade="all, delete-orphan",
        order_by="Message.position",
        lazy="selectin",
    )


class Message(Base, TimestampMixin):
    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("msg"))
    thread_id: Mapped[str] = mapped_column(
        ForeignKey("threads.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = mapped_column(Integer, default=0)
    role: Mapped[str] = mapped_column(String(20))  # user | assistant | tool | system
    content: Mapped[str] = mapped_column(Text, default="")
    reasoning: Mapped[str] = mapped_column(Text, default="")
    # Raw OpenAI-shaped payload so the LLM history round-trips exactly.
    raw: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    attachments: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    meta: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    error: Mapped[str] = mapped_column(Text, default="")
    finished: Mapped[bool] = mapped_column(Boolean, default=True)

    thread: Mapped[Thread] = relationship(back_populates="messages")

    __table_args__ = (Index("ix_messages_thread_position", "thread_id", "position"),)


class Event(Base):
    """Append-only trace of everything the agent did during a turn."""

    __tablename__ = "events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    thread_id: Mapped[str] = mapped_column(
        ForeignKey("threads.id", ondelete="CASCADE"), index=True
    )
    message_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    type: Mapped[str] = mapped_column(String(40))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=None, nullable=True
    )


class ToolCallRecord(Base, TimestampMixin):
    __tablename__ = "tool_calls"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("tc"))
    thread_id: Mapped[str] = mapped_column(
        ForeignKey("threads.id", ondelete="CASCADE"), index=True
    )
    message_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # Provider-assigned id. Unique per assistant turn, but not globally, so it cannot be the PK.
    call_id: Mapped[str] = mapped_column(String(80), index=True)
    name: Mapped[str] = mapped_column(String(120))
    arguments: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    result: Mapped[str] = mapped_column(Text, default="")
    display: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="ok")  # ok | error | denied | running
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)


class Provider(Base, TimestampMixin):
    """An OpenAI/Anthropic-compatible endpoint the user brought."""

    __tablename__ = "providers"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("prv"))
    name: Mapped[str] = mapped_column(String(120), unique=True)
    kind: Mapped[str] = mapped_column(String(30), default="openai")  # openai | anthropic
    base_url: Mapped[str] = mapped_column(String(500))
    api_key_enc: Mapped[str] = mapped_column(Text, default="")
    models: Mapped[list[str]] = mapped_column(JSON, default=list)
    default_model: Mapped[str] = mapped_column(String(160), default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    headers: Mapped[dict[str, str]] = mapped_column(JSON, default=dict)


class Connector(Base, TimestampMixin):
    __tablename__ = "connectors"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("con"))
    service: Mapped[str] = mapped_column(String(60), unique=True)
    token_enc: Mapped[str] = mapped_column(Text, default="")
    account: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class MCPServer(Base, TimestampMixin):
    __tablename__ = "mcp_servers"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("mcp"))
    name: Mapped[str] = mapped_column(String(120), unique=True)
    transport: Mapped[str] = mapped_column(String(20), default="stdio")  # stdio | sse | http
    command: Mapped[str] = mapped_column(String(400), default="")
    args: Mapped[list[str]] = mapped_column(JSON, default=list)
    url: Mapped[str] = mapped_column(String(600), default="")
    env: Mapped[dict[str, str]] = mapped_column(JSON, default=dict)
    headers: Mapped[dict[str, str]] = mapped_column(JSON, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_error: Mapped[str] = mapped_column(Text, default="")
    tool_count: Mapped[int] = mapped_column(Integer, default=0)


class Artifact(Base, TimestampMixin):
    """A file the agent explicitly published for the user (report, chart, export)."""

    __tablename__ = "artifacts"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("art"))
    thread_id: Mapped[str] = mapped_column(
        ForeignKey("threads.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(300), default="")
    kind: Mapped[str] = mapped_column(String(30), default="file")  # file | html | markdown | image
    path: Mapped[str] = mapped_column(String(600), default="")
    content: Mapped[str] = mapped_column(Text, default="")
    size: Mapped[int] = mapped_column(Integer, default=0)


class Memory(Base, TimestampMixin):
    """Durable per-project knowledge the agent writes to itself (Claude-style CLAUDE.md)."""

    __tablename__ = "memories"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("mem"))
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    key: Mapped[str] = mapped_column(String(200))
    value: Mapped[str] = mapped_column(Text, default="")
    scope: Mapped[str] = mapped_column(String(20), default="project")

    __table_args__ = (UniqueConstraint("project_id", "key", name="uq_memory_project_key"),)


class Setting(Base, TimestampMixin):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(120), primary_key=True)
    value: Mapped[Any] = mapped_column(JSON, default=dict)


class UsageStat(Base, TimestampMixin):
    __tablename__ = "usage_stats"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    thread_id: Mapped[str] = mapped_column(String(40), index=True)
    model: Mapped[str] = mapped_column(String(160), default="")
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)


class ScheduledJob(Base, TimestampMixin):
    """Cron-style agent job: runs `prompt` in a thread every `interval_minutes`."""

    __tablename__ = "scheduled_jobs"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("job"))
    name: Mapped[str] = mapped_column(String(200), default="Scheduled run")
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    thread_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    prompt: Mapped[str] = mapped_column(Text, default="")
    interval_minutes: Mapped[int] = mapped_column(Integer, default=60)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_status: Mapped[str] = mapped_column(String(20), default="never")


class ShareLink(Base, TimestampMixin):
    """Public read-only link to a thread."""

    __tablename__ = "share_links"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("shr"))
    thread_id: Mapped[str] = mapped_column(
        ForeignKey("threads.id", ondelete="CASCADE"), index=True
    )
    token: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    role: Mapped[str] = mapped_column(String(20), default="viewer")
    views: Mapped[int] = mapped_column(Integer, default=0)


class ArtifactComment(Base, TimestampMixin):
    __tablename__ = "artifact_comments"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("cmt"))
    artifact_id: Mapped[str] = mapped_column(
        ForeignKey("artifacts.id", ondelete="CASCADE"), index=True
    )
    author: Mapped[str] = mapped_column(String(120), default="you")
    content: Mapped[str] = mapped_column(Text, default="")


class AuditLog(Base):
    """Append-only trail of significant actions."""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    actor: Mapped[str] = mapped_column(String(120), default="local")
    action: Mapped[str] = mapped_column(String(80), index=True)
    detail: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class SubAgent(Base, TimestampMixin):
    """A managed subagent spawned by the main agent or by the user."""

    __tablename__ = "sub_agents"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("sag"))
    thread_id: Mapped[str] = mapped_column(
        ForeignKey("threads.id", ondelete="CASCADE"), index=True
    )
    parent_agent_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    swarm_id: Mapped[str | None] = mapped_column(
        ForeignKey("swarms.id", ondelete="SET NULL"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(200), default="")
    agent_type: Mapped[str] = mapped_column(String(40), default="coder")
    status: Mapped[str] = mapped_column(String(20), default="queued")
    priority: Mapped[str] = mapped_column(String(20), default="normal")
    prompt: Mapped[str] = mapped_column(Text, default="")
    system_extra: Mapped[str] = mapped_column(Text, default="")
    result: Mapped[str] = mapped_column(Text, default="")
    result_summary: Mapped[str] = mapped_column(Text, default="")
    error: Mapped[str] = mapped_column(Text, default="")
    max_steps: Mapped[int] = mapped_column(Integer, default=25)
    steps_completed: Mapped[int] = mapped_column(Integer, default=0)
    tools_allowed: Mapped[list[str]] = mapped_column(JSON, default=list)
    tools_blocked: Mapped[list[str]] = mapped_column(JSON, default=list)
    token_usage: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    meta: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    thread: Mapped[Thread] = relationship(backref="sub_agents")


class Swarm(Base, TimestampMixin):
    """A group of subagents deployed together for a coordinated task."""

    __tablename__ = "swarms"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("swm"))
    thread_id: Mapped[str] = mapped_column(
        ForeignKey("threads.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(200), default="")
    strategy: Mapped[str] = mapped_column(String(30), default="parallel")
    status: Mapped[str] = mapped_column(String(20), default="deploying")
    prompt: Mapped[str] = mapped_column(Text, default="")
    agent_count: Mapped[int] = mapped_column(Integer, default=0)
    completed_count: Mapped[int] = mapped_column(Integer, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, default=0)
    result: Mapped[str] = mapped_column(Text, default="")
    meta: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    thread: Mapped[Thread] = relationship(backref="swarms")
    agents: Mapped[list[SubAgent]] = relationship(backref="swarm")
