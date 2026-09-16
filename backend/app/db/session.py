"""Async SQLAlchemy engine + session factory."""

from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.inspection import inspect
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.base import Base

engine = create_async_engine(
    settings.database_url,
    echo=False,
    pool_pre_ping=True,
    connect_args={"check_same_thread": False} if settings.database_url.startswith("sqlite") else {},
)

SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

# Setup MongoDB automatic state sinking
from app.db.mongo import mongo_manager  # noqa: E402


@event.listens_for(Session, "after_flush")
def sync_to_mongo(session, flush_context):
    if not getattr(mongo_manager, "enabled", False):
        return
        
    for obj in session.new:
        mongo_manager.queue_upsert(obj)
    for obj in session.dirty:
        mongo_manager.queue_upsert(obj)
    for obj in session.deleted:
        try:
            model_cls = type(obj)
            mapper = inspect(model_cls)
            pk_vals = {c.key: getattr(obj, c.key) for c in mapper.primary_key}
            mongo_manager.queue_delete(model_cls, pk_vals)
        except Exception:
            pass


async def init_db() -> None:
    from app.db import models  # noqa: F401  (register mappers)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        
    # Initalize MongoDB connection
    await mongo_manager.init()
    if mongo_manager.enabled:
        async with SessionLocal() as session:
            await mongo_manager.restore_to_sqlite(session)

async def get_db() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session
