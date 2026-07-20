import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.models.search_history import SearchHistory
from app.models.video import Video


@pytest.mark.anyio
async def test_searches_are_recorded_and_rank_matching_titles(db_session, client):
    now = datetime.now(timezone.utc)
    dota_video = Video(
        id=uuid.uuid4(),
        file_path="/media/dota-invoker.mp4",
        title="Dota Invoker Guide",
        file_size=1024,
        file_mtime=now,
        status="ready",
        added_at=now,
        last_seen_at=now,
    )
    football_video = Video(
        id=uuid.uuid4(),
        file_path="/media/football.mp4",
        title="Football Highlights",
        file_size=1024,
        file_mtime=now,
        status="ready",
        added_at=now,
        last_seen_at=now,
    )
    db_session.add_all([dota_video, football_video])
    await db_session.commit()

    for _ in range(2):
        response = await client.get("/api/v1/search?q=Dota")
        assert response.status_code == 200
        assert [item["id"] for item in response.json()] == [str(dota_video.id)]

    history = (
        await db_session.execute(select(SearchHistory).order_by(SearchHistory.searched_at, SearchHistory.id))
    ).scalars().all()
    assert len(history) == 2
    assert all(entry.query == "Dota" and entry.result_count == 1 for entry in history)

    first_feed = await client.get("/api/v1/feed/home?offset=0&limit=2")
    second_feed = await client.get("/api/v1/feed/home?offset=0&limit=2")
    first_items = first_feed.json()["recommendations"]["items"]
    assert first_items[0]["id"] == str(dota_video.id)
    assert first_items[0]["recommendation_reason"] == "Because you searched: dota"
    assert [item["id"] for item in first_items] == [
        item["id"] for item in second_feed.json()["recommendations"]["items"]
    ]
