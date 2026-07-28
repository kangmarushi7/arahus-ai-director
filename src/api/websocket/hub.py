"""WebSocket progress hub for live pipeline / media updates."""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from typing import Any

from src.progress import ProgressUpdate

logger = logging.getLogger(__name__)


class ProgressHub:
    """Fan-out progress events to WebSocket subscribers per project."""

    def __init__(self) -> None:
        self._subscribers: dict[str, set[asyncio.Queue[dict[str, Any]]]] = defaultdict(
            set
        )
        self._lock = asyncio.Lock()

    async def subscribe(self, project_id: str) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=256)
        async with self._lock:
            self._subscribers[project_id].add(queue)
        return queue

    async def unsubscribe(
        self,
        project_id: str,
        queue: asyncio.Queue[dict[str, Any]],
    ) -> None:
        async with self._lock:
            subs = self._subscribers.get(project_id)
            if not subs:
                return
            subs.discard(queue)
            if not subs:
                self._subscribers.pop(project_id, None)

    async def publish(self, project_id: str, event: dict[str, Any]) -> None:
        payload = {"project_id": project_id, **event}
        async with self._lock:
            subscribers = list(self._subscribers.get(project_id, ()))
        for queue in subscribers:
            try:
                queue.put_nowait(payload)
            except asyncio.QueueFull:
                logger.warning(
                    "event=ws_progress_drop project_id=%r type=%r",
                    project_id,
                    event.get("type"),
                )

    def publish_threadsafe(
        self,
        loop: asyncio.AbstractEventLoop,
        project_id: str,
        event: dict[str, Any],
    ) -> None:
        """Publish from a worker thread into the asyncio loop."""
        asyncio.run_coroutine_threadsafe(self.publish(project_id, event), loop)

    def make_progress_callback(
        self,
        loop: asyncio.AbstractEventLoop,
        project_id: str,
    ):
        """Return a :class:`~src.progress.ProgressCallback` bridged to this hub."""

        def _callback(update: ProgressUpdate) -> None:
            self.publish_threadsafe(
                loop,
                project_id,
                {
                    "type": "progress",
                    "message": update.message,
                    "fraction": update.fraction,
                    "stages": dict(update.stages),
                    "stage_panel": update.stage_panel,
                },
            )

        return _callback


# Process-wide hub used by DI.
progress_hub = ProgressHub()
