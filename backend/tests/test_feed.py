import pytest
import uuid
from datetime import datetime, timezone, timedelta
from app.models.video import Video
from app.models.watch_session import WatchSession

@pytest.mark.anyio
async def test_homepage_feed(db_session, client):
    now = datetime.now(timezone.utc)
    
    # 1. Create dummy videos
    v1 = Video(
        id=uuid.uuid4(),
        file_path="/media/lib-a/Arrival.mp4",
        title="Arrival 2016",
        file_size=1024,
        file_mtime=now,
        status="ready",
        added_at=now,
        last_seen_at=now,
    )
    v2 = Video(
        id=uuid.uuid4(),
        file_path="/media/lib-b/interstellar.mp4",
        title="Interstellar",
        file_size=2048,
        file_mtime=now,
        status="ready",
        added_at=now - timedelta(days=1),
        last_seen_at=now,
    )
    v_unavailable = Video(
        id=uuid.uuid4(),
        file_path="/media/lib-x/missing.mp4",
        title="Missing",
        file_size=2048,
        file_mtime=now,
        status="unavailable",
        added_at=now,
        last_seen_at=now,
    )
    v3 = Video(
        id=uuid.uuid4(),
        file_path="/media/lib-b/matrix.mp4",
        title="Matrix",
        file_size=2048,
        file_mtime=now,
        status="ready",
        added_at=now - timedelta(days=2),
        last_seen_at=now,
    )
    v4 = Video(
        id=uuid.uuid4(),
        file_path="/media/lib-b/dune.mp4",
        title="Dune",
        file_size=2048,
        file_mtime=now,
        status="ready",
        added_at=now - timedelta(days=3),
        last_seen_at=now,
    )
    db_session.add_all([v1, v2, v_unavailable, v3, v4])
    await db_session.flush()

    # 2. Add watch sessions
    # Valid continue watching for v1
    ws1 = WatchSession(
        id=uuid.uuid4(),
        video_id=v1.id,
        user_id=None,
        position_seconds=120.5,
        duration_seconds=3600.0,
        completed=False,
    )
    # Completed session for v2
    ws2 = WatchSession(
        id=uuid.uuid4(),
        video_id=v2.id,
        user_id=None,
        position_seconds=3590.0,
        duration_seconds=3600.0,
        completed=True,
    )
    # Unavailable video session for v_unavailable
    ws_unavail = WatchSession(
        id=uuid.uuid4(),
        video_id=v_unavailable.id,
        user_id=None,
        position_seconds=500.0,
        duration_seconds=3600.0,
        completed=False,
    )
    # Session with 0 position for v3
    ws3 = WatchSession(
        id=uuid.uuid4(),
        video_id=v3.id,
        user_id=None,
        position_seconds=0.0,
        duration_seconds=3600.0,
        completed=False,
    )
    db_session.add_all([ws1, ws2, ws_unavail, ws3])
    await db_session.commit()

    # 3. Request feed
    response = await client.get("/api/v1/feed/home")
    assert response.status_code == 200
    data = response.json()

    sections = data["sections"]
    assert len(sections) == 2

    cw_section = next(s for s in sections if s["id"] == "continue_watching")
    # Only v1 should be in continue watching. 
    # ws2 is completed, ws_unavail video is unavailable, ws3 has position_seconds=0
    assert len(cw_section["items"]) == 1
    assert cw_section["items"][0]["id"] == str(v1.id)

    ra_section = next(s for s in sections if s["id"] == "recently_added")
    # All ready videos should be in recently added, ordered by added_at desc. 
    # v_unavailable should be excluded.
    assert len(ra_section["items"]) == 4
    assert ra_section["items"][0]["id"] == str(v1.id)
    assert ra_section["items"][1]["id"] == str(v2.id)
    assert ra_section["items"][2]["id"] == str(v3.id)
    assert ra_section["items"][3]["id"] == str(v4.id)
