import asyncio
import uuid
from types import SimpleNamespace

import pytest

from app.services.asset_queue import AssetGenerationQueue
from app.services.asset_service import AssetService, HOVER_PREVIEW, SEEKBAR_PREVIEW, THUMBNAIL


@pytest.mark.anyio
async def test_thumbnail_queue_priority_and_deduplication():
    queue = AssetGenerationQueue()
    video_id = uuid.uuid4()
    queue.enqueue(video_id, SEEKBAR_PREVIEW)
    queue.enqueue(video_id, SEEKBAR_PREVIEW)
    queue.enqueue(video_id, HOVER_PREVIEW)
    queue.enqueue(video_id, THUMBNAIL)

    assert queue._queue.qsize() == 3
    actual = []
    for _ in range(3):
        _, _, queued_video, queued_type = await queue._queue.get()
        actual.append((queued_video, queued_type))
    assert actual == [(video_id, THUMBNAIL), (video_id, SEEKBAR_PREVIEW), (video_id, HOVER_PREVIEW)]


@pytest.mark.anyio
async def test_worker_count_is_capped_at_two(monkeypatch):
    queue = AssetGenerationQueue()
    active = 0
    peak = 0

    async def no_stale_assets():
        return []

    async def generate(_video_id, _asset_type):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.01)
        active -= 1

    monkeypatch.setattr(AssetService, "mark_stale_thumbnails_pending", no_stale_assets)
    monkeypatch.setattr(AssetService, "mark_stale_previews_pending", no_stale_assets)
    monkeypatch.setattr(AssetService, "generate_asset", generate)
    monkeypatch.setattr("app.services.asset_queue.get_settings", lambda: SimpleNamespace(asset_worker_count=5))
    for _ in range(6):
        queue.enqueue(uuid.uuid4(), THUMBNAIL)

    await queue.start()
    await queue._queue.join()
    await queue.stop()
    assert peak == 2
