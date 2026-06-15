import pytest
import uuid
from datetime import datetime, timezone
from sqlalchemy import select
from app.models.video import Video
from app.models.watch_session import WatchSession


@pytest.mark.anyio
async def test_create_and_update_watch_session(db_session, client):
    # 1. Create a dummy video first
    vid = uuid.uuid4()
    now = datetime.now(timezone.utc)
    video = Video(
        id=vid,
        file_path="/media/lib-a/test-watch.mp4",
        title="Watch Test Video",
        file_size=1024,
        file_mtime=now,
        status="ready",
        added_at=now,
        last_seen_at=now,
    )
    db_session.add(video)
    await db_session.commit()

    # 2. PUT to create watch session (completed=false before threshold)
    payload = {
        "position_seconds": 50.0,
        "duration_seconds": 100.0
    }
    response = await client.put(f"/api/v1/watch/sessions/{vid}", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["video_id"] == str(vid)
    assert data["position_seconds"] == 50.0
    assert data["duration_seconds"] == 100.0
    assert data["completed"] is False

    # Check DB state
    result = await db_session.execute(select(WatchSession).where(WatchSession.video_id == vid))
    sessions = result.scalars().all()
    assert len(sessions) == 1

    # 3. PUT to update watch session (completed=true after threshold, position >= 95% of duration)
    payload_update = {
        "position_seconds": 96.0,
        "duration_seconds": 100.0
    }
    response_update = await client.put(f"/api/v1/watch/sessions/{vid}", json=payload_update)
    assert response_update.status_code == 200
    data_update = response_update.json()
    assert data_update["position_seconds"] == 96.0
    assert data_update["completed"] is True

    # Check that repeated updates do not create duplicate rows
    result = await db_session.execute(select(WatchSession).where(WatchSession.video_id == vid))
    sessions = result.scalars().all()
    assert len(sessions) == 1


@pytest.mark.anyio
async def test_resume_position_retrieval(db_session, client):
    # 1. Create a dummy video and its progress
    vid = uuid.uuid4()
    now = datetime.now(timezone.utc)
    video = Video(
        id=vid,
        file_path="/media/lib-a/test-resume.mp4",
        title="Resume Test Video",
        file_size=1024,
        file_mtime=now,
        status="ready",
        added_at=now,
        last_seen_at=now,
    )
    db_session.add(video)
    await db_session.commit()

    # Verify initially resume is null
    response = await client.get(f"/api/v1/videos/{vid}")
    assert response.status_code == 200
    assert response.json()["resume_position_seconds"] is None

    # PUT watch session
    payload = {
        "position_seconds": 45.67,
        "duration_seconds": 120.0
    }
    response_put = await client.put(f"/api/v1/watch/sessions/{vid}", json=payload)
    assert response_put.status_code == 200

    # Retrieve video metadata and verify resume position
    response_get = await client.get(f"/api/v1/videos/{vid}")
    assert response_get.status_code == 200
    assert response_get.json()["resume_position_seconds"] == 45.67


@pytest.mark.anyio
async def test_missing_video_returns_404(client):
    random_uuid = uuid.uuid4()
    payload = {
        "position_seconds": 10.0,
        "duration_seconds": 100.0
    }
    response = await client.put(f"/api/v1/watch/sessions/{random_uuid}", json=payload)
    assert response.status_code == 404
    assert response.json()["detail"] == "Video not found."


@pytest.mark.anyio
async def test_watch_session_position_validation(db_session, client):
    # 1. Create a dummy video first
    vid = uuid.uuid4()
    now = datetime.now(timezone.utc)
    video = Video(
        id=vid,
        file_path="/media/lib-a/test-validation.mp4",
        title="Validation Test Video",
        file_size=1024,
        file_mtime=now,
        status="ready",
        added_at=now,
        last_seen_at=now,
    )
    db_session.add(video)
    await db_session.commit()

    # Case A: position > duration (returns 422 Unprocessable Entity)
    payload_invalid = {
        "position_seconds": 120.0,
        "duration_seconds": 100.0
    }
    response = await client.put(f"/api/v1/watch/sessions/{vid}", json=payload_invalid)
    assert response.status_code == 422

    # Case B: position == duration (allowed, returns 200)
    payload_equal = {
        "position_seconds": 100.0,
        "duration_seconds": 100.0
    }
    response = await client.put(f"/api/v1/watch/sessions/{vid}", json=payload_equal)
    assert response.status_code == 200
    assert response.json()["completed"] is True

    # Case C: position < duration (allowed, returns 200)
    payload_less = {
        "position_seconds": 50.0,
        "duration_seconds": 100.0
    }
    response = await client.put(f"/api/v1/watch/sessions/{vid}", json=payload_less)
    assert response.status_code == 200
    assert response.json()["completed"] is False
