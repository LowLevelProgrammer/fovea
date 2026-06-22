import pytest
import uuid
from datetime import datetime, timezone, timedelta
from sqlalchemy import select, func
from app.models.video import Video
from app.models.tag import Tag, VideoTag
from app.models.watch_path import WatchPath
from app.services.scan_service import ScanService


@pytest.mark.anyio
async def test_tag_crud_endpoints(db_session, client):
    # 1. Create a dummy video
    vid = uuid.uuid4()
    now = datetime.now(timezone.utc)
    video = Video(
        id=vid,
        file_path="/media/lib-a/video.mp4",
        title="Tag CRUD Video",
        file_size=1024,
        file_mtime=now,
        status="ready",
        added_at=now,
        last_seen_at=now,
    )
    db_session.add(video)
    await db_session.commit()

    # 2. List tags when empty
    response = await client.get("/api/v1/tags")
    assert response.status_code == 200
    assert response.json() == []

    # 3. Patch video tags (create and assign)
    payload = {"tags": ["anime", "Naruto", "favorite"]}
    response = await client.patch(f"/api/v1/videos/{vid}", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert len(data["tags"]) == 3
    tag_names = {t["name"] for t in data["tags"]}
    assert tag_names == {"anime", "Naruto", "favorite"}

    # 4. List tags and verify they exist
    response = await client.get("/api/v1/tags")
    assert response.status_code == 200
    tags_list = response.json()
    assert len(tags_list) == 3
    assert {t["name"] for t in tags_list} == {"anime", "Naruto", "favorite"}

    # Get one of the tags to query details
    tag_id = tags_list[0]["id"]
    tag_name = tags_list[0]["name"]

    response = await client.get(f"/api/v1/tags/{tag_id}")
    assert response.status_code == 200
    tag_detail = response.json()
    assert tag_detail["id"] == tag_id
    assert tag_detail["name"] == tag_name
    assert tag_detail["video_count"] == 1

    # 5. Patch tags again (remove "anime", add "Classic", preserve "Naruto" and "favorite")
    payload = {"tags": ["Naruto", "favorite", "Classic"]}
    response = await client.patch(f"/api/v1/videos/{vid}", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert len(data["tags"]) == 3
    assert {t["name"] for t in data["tags"]} == {"Naruto", "favorite", "Classic"}

    # 6. Verify duplicate prevention (sending duplicate names in request)
    payload = {"tags": ["Naruto", "Naruto", "naruto", "Favorite"]}
    response = await client.patch(f"/api/v1/videos/{vid}", json=payload)
    assert response.status_code == 200
    data = response.json()
    # Should resolve case-insensitively and prevent duplicates:
    # "Naruto", "naruto" resolve to the existing "Naruto"
    # "Favorite" resolves to "favorite"
    assert len(data["tags"]) == 2
    assert {t["name"] for t in data["tags"]} == {"Naruto", "favorite"}


@pytest.mark.anyio
async def test_auto_tag_extraction_and_rescan(db_session, client, tmp_path):
    # 1. Create a watch path in DB pointing to tmp_path
    wp_id = uuid.uuid4()
    wp = WatchPath(
        id=wp_id,
        path=str(tmp_path),
        label="Temp Path",
        scan_recursive=True,
        enabled=True,
    )
    db_session.add(wp)
    await db_session.commit()

    # 2. Create nested directories and a dummy video file on disk
    video_dir = tmp_path / "anime" / "Naruto"
    video_dir.mkdir(parents=True, exist_ok=True)
    video_file = video_dir / "episode1.mp4"
    video_file.write_bytes(b"dummy content")

    # Set mtime back slightly to avoid any timezone/timestamp mismatch
    now = datetime.now(timezone.utc)
    # Perform scan
    result = await ScanService.scan(wp_id)
    assert result.videos_discovered == 1

    # 3. Retrieve video and verify auto-tags
    # Find the created video
    res = await db_session.execute(select(Video))
    video = res.scalars().one()
    
    # Query its tags from endpoint
    response = await client.get(f"/api/v1/videos/{video.id}")
    assert response.status_code == 200
    data = response.json()
    
    # Auto-extracted tags from path: "anime" and "Naruto"
    assert len(data["tags"]) == 2
    assert {t["name"] for t in data["tags"]} == {"anime", "Naruto"}

    # Check database VideoTag sources
    res_assoc = await db_session.execute(select(VideoTag).where(VideoTag.video_id == video.id))
    assocs = res_assoc.scalars().all()
    for assoc in assocs:
        assert assoc.source == "auto"

    # 4. User manually adds a tag ("favorite") and shifts "Naruto" to manual
    payload = {"tags": ["favorite", "Naruto"]}
    response = await client.patch(f"/api/v1/videos/{video.id}", json=payload)
    assert response.status_code == 200
    data = response.json()
    # The video should now have "anime" (auto), "Naruto" (manual), "favorite" (manual)
    assert len(data["tags"]) == 3
    assert {t["name"] for t in data["tags"]} == {"anime", "Naruto", "favorite"}

    # Verify sources in DB
    video_id = video.id
    db_session.expire_all()
    res_assoc = await db_session.execute(select(VideoTag).where(VideoTag.video_id == video_id))
    assocs = {assoc.tag_id: assoc.source for assoc in res_assoc.scalars().all()}
    
    tags_res = await db_session.execute(select(Tag))
    tag_map = {t.name: t.id for t in tags_res.scalars().all()}

    assert assocs[tag_map["anime"]] == "auto"
    assert assocs[tag_map["Naruto"]] == "manual"
    assert assocs[tag_map["favorite"]] == "manual"

    # 5. Move the video file on disk to a different folder structure:
    # "movies" / "SciFi"
    # This should update the auto-tags to "movies" and "SciFi", remove "anime", and preserve manual tags.
    new_video_dir = tmp_path / "movies" / "SciFi"
    new_video_dir.mkdir(parents=True, exist_ok=True)
    new_video_file = new_video_dir / "episode1.mp4"
    new_video_file.write_bytes(b"dummy content")
    
    # Remove the old file
    video_file.unlink()

    # Update the video file_path in DB to simulate rename/move detection matching
    video.file_path = str(new_video_file)
    db_session.add(video)
    await db_session.commit()

    # Trigger rescan
    result = await ScanService.scan(wp_id)
    # 1 disappeared (marked unavailable), 1 discovered (upserted reappearing)
    # The existing video record is re-discovered
    
    # Check tags again
    response = await client.get(f"/api/v1/videos/{video_id}")
    assert response.status_code == 200
    data = response.json()
    
    # Expected tags:
    # - "movies" (auto)
    # - "SciFi" (auto)
    # - "Naruto" (manual - preserved!)
    # - "favorite" (manual - preserved!)
    # Note: "anime" (auto) must be removed since the video path changed and it's no longer in folders.
    assert {t["name"] for t in data["tags"]} == {"movies", "SciFi", "Naruto", "favorite"}


@pytest.mark.anyio
async def test_search_videos(db_session, client):
    # 1. Create 4 videos with distinct titles, title_override, and file_path
    v1 = Video(
        id=uuid.uuid4(),
        file_path="/media/lib-a/Arrival.mp4",
        title="Arrival 2016",
        title_override=None,
        file_size=1024,
        file_mtime=datetime.now(timezone.utc),
        status="ready",
        added_at=datetime.now(timezone.utc),
        last_seen_at=datetime.now(timezone.utc),
    )
    v2 = Video(
        id=uuid.uuid4(),
        file_path="/media/lib-b/sci_fi_movie.mp4",
        title="Interstellar",
        title_override="Arrival at Blackhole",
        file_size=2048,
        file_mtime=datetime.now(timezone.utc),
        status="ready",
        added_at=datetime.now(timezone.utc),
        last_seen_at=datetime.now(timezone.utc),
    )
    v3 = Video(
        id=uuid.uuid4(),
        file_path="/media/lib-c/arrival_trailer_1080p.mp4",
        title="Promo Trailer",
        title_override=None,
        file_size=3072,
        file_mtime=datetime.now(timezone.utc),
        status="ready",
        added_at=datetime.now(timezone.utc),
        last_seen_at=datetime.now(timezone.utc),
    )
    v4 = Video(
        id=uuid.uuid4(),
        file_path="/media/lib-d/unrelated_filename.mp4",
        title="Something Else",
        title_override=None,
        file_size=4096,
        file_mtime=datetime.now(timezone.utc),
        status="ready",
        added_at=datetime.now(timezone.utc),
        last_seen_at=datetime.now(timezone.utc),
    )
    db_session.add_all([v1, v2, v3, v4])
    await db_session.flush()

    # Create tag "Arrival" and associate with v4
    tag = Tag(name="Arrival")
    db_session.add(tag)
    await db_session.flush()

    assoc = VideoTag(video_id=v4.id, tag_id=tag.id, source="manual")
    db_session.add(assoc)
    await db_session.commit()

    # 2. Search for "arrival" case-insensitively
    response = await client.get("/api/v1/search?q=arrival")
    assert response.status_code == 200
    data = response.json()
    
    assert len(data) == 4
    # Relevance sort validation:
    # First: Match in title_override (v2: "Arrival at Blackhole" has score 4)
    # Second: Match in title (v1: "Arrival 2016" has score 3)
    # Third: Match in tag (v4: associated with tag "Arrival" has score 2)
    # Fourth: Match in file_path (v3: "/media/lib-c/arrival_trailer_1080p.mp4" has score 1)
    assert data[0]["id"] == str(v2.id)
    assert data[1]["id"] == str(v1.id)
    assert data[2]["id"] == str(v4.id)
    assert data[3]["id"] == str(v3.id)


@pytest.mark.anyio
async def test_patch_video_tags_regression(db_session, client):
    # Setup video
    v1 = Video(
        id=uuid.uuid4(),
        file_path="/media/lib-a/Regression.mp4",
        title="Regression Test",
        file_size=1024,
        file_mtime=datetime.now(timezone.utc),
        status="ready",
        added_at=datetime.now(timezone.utc),
        last_seen_at=datetime.now(timezone.utc),
    )
    db_session.add(v1)
    await db_session.flush()

    # Create tag for auto-tag
    t_auto = Tag(name="auto_tag")
    db_session.add(t_auto)
    await db_session.flush()
    
    # Create auto tag association
    assoc = VideoTag(video_id=v1.id, tag_id=t_auto.id, source="auto")
    db_session.add(assoc)
    await db_session.commit()

    # 1. Patch: manual promotion of auto_tag, addition of new_manual, deletion of nothing (since nothing else exists)
    payload = {"tags": ["auto_tag", "new_manual"]}
    response = await client.patch(f"/api/v1/videos/{v1.id}", json=payload)
    assert response.status_code == 200
    data = response.json()
    
    # Verify response payload correctness
    assert len(data["tags"]) == 2
    tag_names = {t["name"] for t in data["tags"]}
    assert tag_names == {"auto_tag", "new_manual"}

    # Verify db state: auto_tag should be manual now
    v1_id = v1.id
    db_session.expire_all()
    res = await db_session.execute(select(VideoTag).where(VideoTag.video_id == v1_id))
    assocs = {str(a.tag_id): a.source for a in res.scalars().all()}
    
    tag_res = await db_session.execute(select(Tag).where(Tag.name.in_(["auto_tag", "new_manual"])))
    tag_map = {t.name: str(t.id) for t in tag_res.scalars().all()}
    
    assert assocs[tag_map["auto_tag"]] == "manual"
    assert assocs[tag_map["new_manual"]] == "manual"

    # 2. Patch: manual removal of new_manual
    payload = {"tags": ["auto_tag"]}
    response = await client.patch(f"/api/v1/videos/{v1_id}", json=payload)
    assert response.status_code == 200
    data = response.json()
    
    assert len(data["tags"]) == 1
    assert data["tags"][0]["name"] == "auto_tag"

    # Verify db state
    db_session.expire_all()
    res = await db_session.execute(select(VideoTag).where(VideoTag.video_id == v1_id))
    remaining_assocs = res.scalars().all()
    assert len(remaining_assocs) == 1
    assert str(remaining_assocs[0].tag_id) == tag_map["auto_tag"]
    assert remaining_assocs[0].source == "manual"
