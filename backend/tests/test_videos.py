import pytest
import uuid
from datetime import datetime, timezone, timedelta
from app.models.video import Video


@pytest.mark.anyio
async def test_list_videos(db_session, client):
    # Create 3 videos: 2 available, 1 unavailable
    v1_id = uuid.uuid4()
    v2_id = uuid.uuid4()
    v3_id = uuid.uuid4()

    now = datetime.now(timezone.utc)

    video1 = Video(
        id=v1_id,
        file_path="/media/lib-a/video1.mp4",
        title="Video 1",
        file_size=1024,
        file_mtime=now,
        status="ready",
        added_at=now - timedelta(hours=1),
        last_seen_at=now,
    )
    video2 = Video(
        id=v2_id,
        file_path="/media/lib-a/video2.mp4",
        title="Video 2",
        file_size=2048,
        file_mtime=now,
        status="unavailable",
        added_at=now,
        last_seen_at=now,
    )
    video3 = Video(
        id=v3_id,
        file_path="/media/lib-a/video3.mp4",
        title="Video 3",
        file_size=3072,
        file_mtime=now,
        status="discovered",
        added_at=now + timedelta(hours=1),
        last_seen_at=now,
    )

    db_session.add_all([video1, video2, video3])
    await db_session.commit()

    # Call GET /api/v1/videos
    response = await client.get("/api/v1/videos")
    assert response.status_code == 200
    data = response.json()

    # Unavailable video (video2) must be excluded.
    # Available videos (video3 and video1) must be sorted by added_at DESC.
    # So order should be: video3, then video1.
    assert len(data["items"]) == 2
    assert data["items"][0]["id"] == str(v3_id)
    assert data["items"][1]["id"] == str(v1_id)

    # Verify response schema fields are present
    item = data["items"][0]
    assert "id" in item
    assert "title" in item
    assert "file_path" in item
    assert "status" in item
    assert "added_at" in item


@pytest.mark.anyio
async def test_get_video_metadata(db_session, client):
    vid = uuid.uuid4()
    now = datetime.now(timezone.utc)
    video = Video(
        id=vid,
        file_path="/media/lib-a/video.mp4",
        title="Video Meta Test",
        file_size=1024,
        file_mtime=now,
        status="ready",
        added_at=now,
        last_seen_at=now,
    )
    db_session.add(video)
    await db_session.commit()

    # Existent video
    response = await client.get(f"/api/v1/videos/{vid}")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == str(vid)
    assert data["title"] == "Video Meta Test"
    assert data["status"] == "ready"
    assert data["file_size"] == 1024

    # Non-existent video
    random_uuid = uuid.uuid4()
    response = await client.get(f"/api/v1/videos/{random_uuid}")
    assert response.status_code == 404
    assert response.json()["detail"] == "Video not found."


@pytest.mark.anyio
async def test_stream_video_full(db_session, client, tmp_path):
    # Create a dummy file on disk
    dummy_file = tmp_path / "stream_full.mp4"
    dummy_content = b"0123456789" * 100  # 1000 bytes
    dummy_file.write_bytes(dummy_content)

    vid = uuid.uuid4()
    now = datetime.now(timezone.utc)
    video = Video(
        id=vid,
        file_path=str(dummy_file),
        title="Stream Test Full",
        file_size=len(dummy_content),
        file_mtime=now,
        status="ready",
        added_at=now,
        last_seen_at=now,
    )
    db_session.add(video)
    await db_session.commit()

    # Stream full video without Range header
    response = await client.get(f"/api/v1/videos/{vid}/stream")
    assert response.status_code == 200
    assert response.headers["Accept-Ranges"] == "bytes"
    assert response.headers["Content-Length"] == "1000"
    assert response.headers["Content-Type"] == "video/mp4"
    assert response.content == dummy_content


@pytest.mark.anyio
async def test_stream_video_range(db_session, client, tmp_path):
    dummy_file = tmp_path / "stream_range.mp4"
    dummy_content = b"abcdefghij" * 100  # 1000 bytes
    dummy_file.write_bytes(dummy_content)

    vid = uuid.uuid4()
    now = datetime.now(timezone.utc)
    video = Video(
        id=vid,
        file_path=str(dummy_file),
        title="Stream Test Range",
        file_size=len(dummy_content),
        file_mtime=now,
        status="ready",
        added_at=now,
        last_seen_at=now,
    )
    db_session.add(video)
    await db_session.commit()

    # Stream partial content with Range header (bytes=100-199)
    response = await client.get(
        f"/api/v1/videos/{vid}/stream",
        headers={"Range": "bytes=100-199"}
    )
    assert response.status_code == 206
    assert response.headers["Accept-Ranges"] == "bytes"
    assert response.headers["Content-Length"] == "100"
    assert response.headers["Content-Range"] == "bytes 100-199/1000"
    assert response.content == dummy_content[100:200]

    # Stream partial content with prefix Range (bytes=500-)
    response = await client.get(
        f"/api/v1/videos/{vid}/stream",
        headers={"Range": "bytes=500-"}
    )
    assert response.status_code == 206
    assert response.headers["Content-Length"] == "500"
    assert response.headers["Content-Range"] == "bytes 500-999/1000"
    assert response.content == dummy_content[500:]

    # Stream partial content with suffix Range (bytes=-200)
    response = await client.get(
        f"/api/v1/videos/{vid}/stream",
        headers={"Range": "bytes=-200"}
    )
    assert response.status_code == 206
    assert response.headers["Content-Length"] == "200"
    assert response.headers["Content-Range"] == "bytes 800-999/1000"
    assert response.content == dummy_content[800:]


@pytest.mark.anyio
async def test_stream_video_range_coercion(db_session, client, tmp_path):
    dummy_file = tmp_path / "stream_coercion.mp4"
    dummy_content = b"0123456789" * 10  # 100 bytes
    dummy_file.write_bytes(dummy_content)

    vid = uuid.uuid4()
    now = datetime.now(timezone.utc)
    video = Video(
        id=vid,
        file_path=str(dummy_file),
        title="Stream Test Range Coercion",
        file_size=len(dummy_content),
        file_mtime=now,
        status="ready",
        added_at=now,
        last_seen_at=now,
    )
    db_session.add(video)
    await db_session.commit()

    # Range request exceeding file size (bytes=50-999999) -> Coerced to 50-99
    response = await client.get(
        f"/api/v1/videos/{vid}/stream",
        headers={"Range": "bytes=50-999999"}
    )
    assert response.status_code == 206
    assert response.headers["Content-Length"] == "50"
    assert response.headers["Content-Range"] == "bytes 50-99/100"
    assert response.content == dummy_content[50:]


@pytest.mark.anyio
async def test_stream_video_multi_range(db_session, client, tmp_path):
    dummy_file = tmp_path / "stream_multi.mp4"
    dummy_content = b"abcdefghij" * 10  # 100 bytes
    dummy_file.write_bytes(dummy_content)

    vid = uuid.uuid4()
    now = datetime.now(timezone.utc)
    video = Video(
        id=vid,
        file_path=str(dummy_file),
        title="Stream Test Multi-Range",
        file_size=len(dummy_content),
        file_mtime=now,
        status="ready",
        added_at=now,
        last_seen_at=now,
    )
    db_session.add(video)
    await db_session.commit()

    # Multi-range request (bytes=10-19,50-59) -> Fallback to first range
    response = await client.get(
        f"/api/v1/videos/{vid}/stream",
        headers={"Range": "bytes=10-19,50-59"}
    )
    assert response.status_code == 206
    assert response.headers["Content-Length"] == "10"
    assert response.headers["Content-Range"] == "bytes 10-19/100"
    assert response.content == dummy_content[10:20]


@pytest.mark.anyio
async def test_stream_video_invalid_range(db_session, client, tmp_path):
    dummy_file = tmp_path / "stream_invalid.mp4"
    dummy_content = b"0123456789" * 10  # 100 bytes
    dummy_file.write_bytes(dummy_content)

    vid = uuid.uuid4()
    now = datetime.now(timezone.utc)
    video = Video(
        id=vid,
        file_path=str(dummy_file),
        title="Stream Test Invalid Range",
        file_size=len(dummy_content),
        file_mtime=now,
        status="ready",
        added_at=now,
        last_seen_at=now,
    )
    db_session.add(video)
    await db_session.commit()

    # Out of bounds range (bytes=100-120)
    response = await client.get(
        f"/api/v1/videos/{vid}/stream",
        headers={"Range": "bytes=100-120"}
    )
    assert response.status_code == 416
    assert response.headers["Content-Range"] == "bytes */100"

    # Start > end (bytes=50-20)
    response = await client.get(
        f"/api/v1/videos/{vid}/stream",
        headers={"Range": "bytes=50-20"}
    )
    assert response.status_code == 416
    assert response.headers["Content-Range"] == "bytes */100"


@pytest.mark.anyio
async def test_stream_video_unavailable(db_session, client):
    vid = uuid.uuid4()
    now = datetime.now(timezone.utc)
    video = Video(
        id=vid,
        file_path="/media/lib-a/unavailable.mp4",
        title="Unavailable Stream Video",
        file_size=1024,
        file_mtime=now,
        status="unavailable",
        added_at=now,
        last_seen_at=now,
    )
    db_session.add(video)
    await db_session.commit()

    response = await client.get(f"/api/v1/videos/{vid}/stream")
    assert response.status_code == 410
    assert response.json()["detail"] == "Video is unavailable."


@pytest.mark.anyio
async def test_stream_video_missing_file_on_disk(db_session, client):
    vid = uuid.uuid4()
    now = datetime.now(timezone.utc)
    video = Video(
        id=vid,
        file_path="/media/lib-a/missing_on_disk.mp4",
        title="Missing File On Disk Video",
        file_size=1024,
        file_mtime=now,
        status="ready",
        added_at=now,
        last_seen_at=now,
    )
    db_session.add(video)
    await db_session.commit()

    # Backing file doesn't exist on disk -> Returns 410 Gone
    response = await client.get(f"/api/v1/videos/{vid}/stream")
    assert response.status_code == 410
    assert response.json()["detail"] == "Video file not found on disk."


@pytest.mark.anyio
async def test_stream_video_missing(client):
    random_uuid = uuid.uuid4()
    response = await client.get(f"/api/v1/videos/{random_uuid}/stream")
    assert response.status_code == 404
    assert response.json()["detail"] == "Video not found."
