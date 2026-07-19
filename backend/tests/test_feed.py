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

    continue_watching = data["continue_watching"]
    # Only v1 should be in continue watching. 
    # ws2 is completed, ws_unavail video is unavailable, ws3 has position_seconds=0
    assert len(continue_watching) == 1
    assert continue_watching[0]["id"] == str(v1.id)
    assert continue_watching[0]["resume_position_seconds"] == 120.5
    assert continue_watching[0]["duration_seconds"] == 3600.0
    assert continue_watching[0]["completed"] is False

    recommendations = data["recommendations"]
    assert recommendations["total"] == 3
    assert recommendations["has_more"] is False
    item_ids = {item["id"] for item in recommendations["items"]}
    assert item_ids == {str(v2.id), str(v3.id), str(v4.id)}
    completed_item = next(item for item in recommendations["items"] if item["id"] == str(v2.id))
    assert completed_item["completed"] is True

@pytest.mark.anyio
async def test_recommendation_feed(db_session, client):
    from app.models.tag import Tag, VideoTag
    
    # Need sufficient videos to test random injection and duplication logic
    now = datetime.now(timezone.utc)
    videos = []
    for i in range(40):
        v = Video(
            id=uuid.uuid4(),
            file_path=f"/media/lib-r/rec{i}.mp4",
            title=f"Rec {i}",
            file_size=1024,
            file_mtime=now,
            status="ready",
            added_at=now - timedelta(days=20 if i < 5 else 10),
            last_seen_at=now,
            watch_count=0
        )
        videos.append(v)
    db_session.add_all(videos)
    await db_session.flush()

    # Create a tag
    tag_scifi = Tag(name="sci-fi")
    tag_action = Tag(name="action")
    db_session.add_all([tag_scifi, tag_action])
    await db_session.flush()

    # User watched videos[0] and videos[1], which has sci-fi and action tags
    ws1 = WatchSession(id=uuid.uuid4(), video_id=videos[0].id, user_id=None, position_seconds=100, duration_seconds=1000, completed=True)
    ws2 = WatchSession(id=uuid.uuid4(), video_id=videos[1].id, user_id=None, position_seconds=100, duration_seconds=1000, completed=False)
    db_session.add_all([ws1, ws2])
    
    # Tag videos
    db_session.add_all([
        VideoTag(video_id=videos[0].id, tag_id=tag_scifi.id, source="auto"),
        VideoTag(video_id=videos[1].id, tag_id=tag_action.id, source="auto"),
        VideoTag(video_id=videos[2].id, tag_id=tag_scifi.id, source="auto"),
        VideoTag(video_id=videos[3].id, tag_id=tag_action.id, source="auto"),
        VideoTag(video_id=videos[4].id, tag_id=tag_scifi.id, source="auto"),
    ])
    await db_session.commit()

    # Fetch feed
    response = await client.get("/api/v1/feed/home?offset=0&limit=12")
    assert response.status_code == 200
    data = response.json()
    
    page = data["recommendations"]
    items = page["items"]
    assert page["total"] == 39  # The in-progress video is held in Continue Watching.
    assert page["has_more"] is True
    item_ids = [i["id"] for i in items]
    assert str(videos[1].id) not in item_ids
    
    # Check that recommendation reasons are present
    reasons = [i["recommendation_reason"] for i in items if i.get("recommendation_reason")]
    assert len(reasons) == len(items)
    
    # Interest profile and exploration reasons are explanation labels, not sections.
    assert any("Shared tag" in r for r in reasons)
    assert len(item_ids) == len(set(item_ids))

    second_page = await client.get("/api/v1/feed/home?offset=12&limit=12")
    second_item_ids = {item["id"] for item in second_page.json()["recommendations"]["items"]}
    assert not set(item_ids).intersection(second_item_ids)

    repeated_page = await client.get("/api/v1/feed/home?offset=0&limit=12")
    assert [item["id"] for item in repeated_page.json()["recommendations"]["items"]] == item_ids
