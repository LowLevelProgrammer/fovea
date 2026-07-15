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

@pytest.mark.anyio
async def test_recommendation_feed(db_session, client):
    from app.models.tag import Tag, VideoTag
    import random
    
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
    response = await client.get("/api/v1/feed/home")
    assert response.status_code == 200
    data = response.json()
    
    sections = data["sections"]
    
    rec_section = next((s for s in sections if s["type"] == "recommended"), None)
    assert rec_section is not None
    
    items = rec_section["items"]
    # We expect some items. limit=12. 
    # Approx 20% random injection = 2 random items (max(1, int(12*0.2)) = 2)
    # The remaining 10 are filled. We only have 13 other videos, so it should fill it up.
    
    # Check that watched videos (videos[0], videos[1]) are EXCLUDED from Recommended For You
    item_ids = [i["id"] for i in items]
    assert str(videos[0].id) not in item_ids
    assert str(videos[1].id) not in item_ids
    
    # Check that recommendation reasons are present
    reasons = [i["recommendation_reason"] for i in items if i.get("recommendation_reason")]
    assert len(reasons) == len(items)
    
    # At least some should be Shared tag
    assert any("Shared tag" in r for r in reasons)
    # At least some should be Random pick
    assert any("Random pick" in r for r in reasons)
    
    # Random discovery section should also exist and have random picks
    random_section = next((s for s in sections if s["type"] == "random"), None)
    assert random_section is not None
    assert len(random_section["items"]) > 0
    assert all(i["recommendation_reason"] == "Random pick" for i in random_section["items"])
    
    # Ensure no duplicates between random discovery and recommended
    rec_ids = set(item_ids)
    rand_ids = set(i["id"] for i in random_section["items"])
    assert rec_ids.isdisjoint(rand_ids), "Random discovery should not duplicate items from recommended"
