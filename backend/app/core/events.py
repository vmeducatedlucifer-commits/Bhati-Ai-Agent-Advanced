"""In-process pub/sub so multiple clients can follow one agent run.

A run publishes events once; the chat stream, the "agent computer" panel, and any
reconnecting browser tab all subscribe to the same topic. Events are also buffered
per topic so a client that connects mid-run gets the backlog before live deltas.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict, deque
from collections.abc import AsyncIterator
from typing import Any

from app.core.logging import get_logger

log = get_logger("app.events")

_BUFFER_SIZE = 2000


class EventBus:
    def __init__(self) -> None:
        self._subscribers: dict[str, set[asyncio.Queue]] = defaultdict(set)
        self._buffers: dict[str, deque[dict[str, Any]]] = defaultdict(
            lambda: deque(maxlen=_BUFFER_SIZE)
        )
        self._seq: dict[str, int] = defaultdict(int)
        self._lock = asyncio.Lock()

    async def publish(self, topic: str, event: dict[str, Any]) -> dict[str, Any]:
        self._seq[topic] += 1
        enriched = {**event, "seq": self._seq[topic]}
        self._buffers[topic].append(enriched)
        for queue in list(self._subscribers.get(topic, ())):
            try:
                queue.put_nowait(enriched)
            except asyncio.QueueFull:
                log.warning("dropping event for slow subscriber on %s", topic)
        return enriched

    def backlog(self, topic: str, after_seq: int = 0) -> list[dict[str, Any]]:
        return [e for e in self._buffers.get(topic, ()) if e.get("seq", 0) > after_seq]

    async def subscribe(
        self, topic: str, *, after_seq: int = 0
    ) -> AsyncIterator[dict[str, Any]]:
        queue: asyncio.Queue = asyncio.Queue(maxsize=4096)
        async with self._lock:
            self._subscribers[topic].add(queue)
        try:
            for event in self.backlog(topic, after_seq):
                yield event
            while True:
                yield await queue.get()
        finally:
            async with self._lock:
                self._subscribers[topic].discard(queue)
                if not self._subscribers[topic]:
                    self._subscribers.pop(topic, None)

    def clear(self, topic: str) -> None:
        self._buffers.pop(topic, None)
        self._seq.pop(topic, None)

    def subscriber_count(self, topic: str) -> int:
        return len(self._subscribers.get(topic, ()))


bus = EventBus()
