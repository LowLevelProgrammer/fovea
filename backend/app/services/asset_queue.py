import asyncio
import itertools
import logging
from uuid import UUID

from app.core.config import get_settings
from app.services.asset_service import AssetService, HOVER_PREVIEW, SEEKBAR_PREVIEW, THUMBNAIL

logger = logging.getLogger(__name__)


class AssetGenerationQueue:
    """Bounded, deduplicated in-process queue for generated asset work."""

    def __init__(self) -> None:
        self._queue: asyncio.PriorityQueue[tuple[int, int, UUID, str]] = asyncio.PriorityQueue()
        self._queued: set[tuple[UUID, str]] = set()
        self._tasks: list[asyncio.Task] = []
        self._sequence = itertools.count()

    async def start(self) -> None:
        if self._tasks:
            return
        for video_id in await AssetService.mark_stale_thumbnails_pending():
            self.enqueue(video_id, THUMBNAIL)
        for video_id in await AssetService.mark_stale_previews_pending():
            self.enqueue(video_id, SEEKBAR_PREVIEW)
        self._tasks = [
            asyncio.create_task(self._worker(index))
            for index in range(max(1, min(2, get_settings().asset_worker_count)))
        ]

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._tasks = []
        self._queued.clear()
        self._queue = asyncio.PriorityQueue()
        self._sequence = itertools.count()

    def enqueue(self, video_id: UUID, asset_type: str = THUMBNAIL) -> None:
        task = (video_id, asset_type)
        if task not in self._queued:
            self._queued.add(task)
            priority = {THUMBNAIL: 0, SEEKBAR_PREVIEW: 10, HOVER_PREVIEW: 20}.get(asset_type, 20)
            self._queue.put_nowait((priority, next(self._sequence), video_id, asset_type))

    async def _worker(self, worker_id: int) -> None:
        while True:
            _, _, video_id, asset_type = await self._queue.get()
            try:
                await AssetService.generate_asset(video_id, asset_type)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Asset worker %s failed for video %s", worker_id, video_id)
            finally:
                self._queued.discard((video_id, asset_type))
                self._queue.task_done()


asset_queue = AssetGenerationQueue()
