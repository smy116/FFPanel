from __future__ import annotations

import asyncio
import json
from collections import defaultdict, deque
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any


class EventBus:
    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self._sequence = 0
        self._lock = asyncio.Lock()
        self._logs: dict[str, deque[dict[str, Any]]] = defaultdict(lambda: deque(maxlen=300))

    async def publish(
        self,
        event_type: str,
        payload: dict[str, Any],
        *,
        task_id: str | None = None,
        file_id: str | None = None,
        version: int = 0,
    ) -> dict[str, Any]:
        async with self._lock:
            self._sequence += 1
            event = {
                "id": str(self._sequence),
                "type": event_type,
                "version": version,
                "taskId": task_id,
                "fileId": file_id,
                "updatedAt": datetime.now(UTC).isoformat(),
                "payload": payload,
            }
            for queue in tuple(self._subscribers):
                try:
                    queue.put_nowait(event)
                except asyncio.QueueFull:
                    try:
                        queue.get_nowait()
                        queue.put_nowait(event)
                    except (asyncio.QueueEmpty, asyncio.QueueFull):
                        pass
            return event

    async def log(self, task_id: str, level: str, message: str, file_id: str | None = None) -> None:
        item = {
            "level": level,
            "message": message,
            "fileId": file_id,
            "createdAt": datetime.now(UTC).isoformat(),
        }
        self._logs[task_id].append(item)
        await self.publish("log.append", item, task_id=task_id, file_id=file_id)

    def recent_logs(self, task_id: str) -> list[dict[str, Any]]:
        return list(self._logs[task_id])

    @asynccontextmanager
    async def subscribe(self) -> AsyncIterator[asyncio.Queue[dict[str, Any]]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=256)
        self._subscribers.add(queue)
        try:
            yield queue
        finally:
            self._subscribers.discard(queue)

    @staticmethod
    def encode_sse(event: dict[str, Any]) -> str:
        return f"id: {event['id']}\nevent: {event['type']}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"

