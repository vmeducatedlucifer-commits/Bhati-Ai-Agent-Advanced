"""MongoDB Asynchronous Persistence and Auto-Sync Engine.

Ensures complete, zero-data-loss cross-deployment persistence for Render, Railway,
or any containerized environment without persistent disks.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.inspection import inspect

from app.core.config import settings
from app.core.logging import get_logger

from .models import (
    Artifact,
    ArtifactComment,
    AuditLog,
    Connector,
    Event,
    MCPServer,
    Memory,
    Message,
    Project,
    Provider,
    ScheduledJob,
    Setting,
    ShareLink,
    Thread,
    ToolCallRecord,
    UsageStat,
)

log = get_logger("app.mongo")

# Ordered carefully by foreign-key dependencies for clean relational insertion
MODELS: list[type] = [
    Project,
    Thread,
    Message,
    Event,
    ToolCallRecord,
    Provider,
    Connector,
    MCPServer,
    Artifact,
    ArtifactComment,
    Memory,
    Setting,
    UsageStat,
    ScheduledJob,
    ShareLink,
    AuditLog,
]


class MongoManager:
    def __init__(self) -> None:
        self.client = None
        self.db = None
        self.enabled = False
        self._is_restoring = False
        self._sync_queue: asyncio.Queue = asyncio.Queue(maxsize=10000)
        self._worker_task: asyncio.Task | None = None

    async def init(self) -> None:
        uri = settings.mongo_uri
        if not uri:
            log.info("MongoDB disabled: no MONGO_URI/MONGODB_URI configured.")
            return

        try:
            import motor.motor_asyncio
            self.client = motor.motor_asyncio.AsyncIOMotorClient(
                uri,
                serverSelectionTimeoutMS=10000,
                connectTimeoutMS=10000,
                socketTimeoutMS=15000,
            )
            db_name = settings.database_name
            self.db = self.client[db_name]

            # Verify connection with ping
            await self.client.admin.command("ping")
            self.enabled = True
            log.info("Connected to MongoDB successfully (database: %s). Real-time persistence ACTIVE.", db_name)

            # Start the background replication worker
            if self._worker_task is None or self._worker_task.done():
                self._worker_task = asyncio.create_task(self._worker())
        except Exception as exc:
            log.error("Failed to connect to MongoDB: %s", exc)
            self.enabled = False

    async def shutdown(self) -> None:
        if self._worker_task and not self._worker_task.done():
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
        if self.client:
            self.client.close()
            log.info("MongoDB client closed.")

    def _to_dict(self, obj: Any) -> dict[str, Any]:
        """Convert a SQLAlchemy ORM model to a clean JSON-serializable MongoDB document."""
        mapper = inspect(type(obj))
        data: dict[str, Any] = {}
        for column in mapper.columns:
            val = getattr(obj, column.key, None)
            if isinstance(val, datetime):
                # Ensure valid ISO string or native UTC datetime for Mongo
                if val.tzinfo is None:
                    val = val.replace(tzinfo=UTC)
            data[column.key] = val
        return data

    def _from_dict(self, model_cls: type, doc: dict[str, Any]) -> Any:
        """Safely instantiate an ORM model from a MongoDB document, handling type conversions."""
        doc = dict(doc)
        doc.pop("_id", None)  # Remove MongoDB internal ObjectId

        mapper = inspect(model_cls)
        valid_keys = {c.key for c in mapper.columns}

        cleaned: dict[str, Any] = {}
        for key, val in doc.items():
            if key not in valid_keys:
                continue

            column = mapper.columns[key]
            # Handle datetime fields if returned as ISO string
            if hasattr(column.type, "python_type") and issubclass(column.type.python_type, datetime):
                if isinstance(val, str):
                    try:
                        cleaned[key] = datetime.fromisoformat(val)
                        continue
                    except Exception:
                        pass

            cleaned[key] = val

        return model_cls(**cleaned)

    async def restore_to_sqlite(self, session: AsyncSession) -> None:
        """Restore all documents from MongoDB collections into local SQLite on startup."""
        if not self.enabled or self.db is None:
            return

        self._is_restoring = True
        log.info("Checking MongoDB for data to restore...")
        total_restored = 0

        try:
            for model_cls in MODELS:
                table_name = model_cls.__tablename__
                coll = self.db[table_name]

                # Check if SQLite already has rows for this model (e.g. if disk was persisted)
                existing = (await session.execute(select(model_cls))).scalars().first()
                if existing is not None:
                    continue

                cursor = coll.find({})
                docs = await cursor.to_list(length=None)
                if not docs:
                    continue

                log.info("Restoring %d records into table '%s'...", len(docs), table_name)
                seen_keys: set[Any] = set()
                for doc in docs:
                    try:
                        obj = self._from_dict(model_cls, doc)

                        # Deduplicate unique constraints to prevent SQLite IntegrityError
                        if model_cls == Connector:
                            if obj.service in seen_keys:
                                continue
                            seen_keys.add(obj.service)
                        elif model_cls == Provider:
                            if obj.name in seen_keys:
                                continue
                            seen_keys.add(obj.name)
                        elif model_cls == MCPServer:
                            if obj.name in seen_keys:
                                continue
                            seen_keys.add(obj.name)
                        elif model_cls == Setting:
                            if obj.key in seen_keys:
                                continue
                            seen_keys.add(obj.key)

                        await session.merge(obj)
                        total_restored += 1
                    except Exception as err:
                        log.warning("Skipped restoring invalid record in '%s': %s", table_name, err)

                try:
                    await session.commit()
                except Exception as commit_err:
                    log.error("Failed to commit restored table '%s': %s", table_name, commit_err)
                    await session.rollback()

            if total_restored > 0:
                log.info("MongoDB restore finished. Restored %d total records into SQLite.", total_restored)
            else:
                log.info("No prior data found in MongoDB or local database already up to date.")
        except Exception as exc:
            log.error("Error during MongoDB restore: %s", exc)
        finally:
            self._is_restoring = False

    def queue_upsert(self, obj: Any) -> None:
        """Queue an object to be asynchronously saved to MongoDB."""
        if not self.enabled or self._is_restoring or self.db is None:
            return

        try:
            model_cls = type(obj)
            if model_cls not in MODELS:
                return

            mapper = inspect(model_cls)
            pk_cols = [c.key for c in mapper.primary_key]

            data = self._to_dict(obj)
            query = {k: data[k] for k in pk_cols if k in data}
            if not query:
                return

            collection_name = model_cls.__tablename__
            self._sync_queue.put_nowait(("upsert", collection_name, query, data))
        except Exception as exc:
            log.warning("Failed to queue MongoDB upsert: %s", exc)

    def queue_delete(self, model_cls: type, pk_values: dict[str, Any]) -> None:
        """Queue an object deletion from MongoDB."""
        if not self.enabled or self._is_restoring or self.db is None:
            return

        try:
            if model_cls not in MODELS or not pk_values:
                return
            collection_name = model_cls.__tablename__
            self._sync_queue.put_nowait(("delete", collection_name, pk_values, None))
        except Exception as exc:
            log.warning("Failed to queue MongoDB delete: %s", exc)

    async def _worker(self) -> None:
        """Continuous async worker that flushes queued database changes to MongoDB collections."""
        log.info("MongoDB sync worker started.")
        while True:
            try:
                op, coll_name, query, data = await self._sync_queue.get()
                if self.db is None:
                    self._sync_queue.task_done()
                    continue

                collection = self.db[coll_name]
                if op == "upsert" and data is not None:
                    await collection.replace_one(query, data, upsert=True)
                elif op == "delete":
                    await collection.delete_one(query)

                self._sync_queue.task_done()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                log.error("MongoDB background sync error: %s", exc)
                await asyncio.sleep(1)


mongo_manager = MongoManager()
