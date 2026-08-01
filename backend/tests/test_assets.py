import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.models.video import Video
from app.models.video_asset import VideoAsset
from app.models.video_probe import VideoProbe
from app.services.asset_service import AssetService


@pytest.mark.anyio
async def test_manual_thumbnail_request_persists_pending_manual_asset(db_session, client):
    now = datetime.now(timezone.utc)
    video = Video(
        id=uuid.uuid4(),
        file_path="/media/example.mp4",
        title="Example",
        file_size=1024,
        file_mtime=now,
        status="ready",
        added_at=now,
        last_seen_at=now,
    )
    db_session.add(video)
    await db_session.commit()

    response = await client.post(f"/api/v1/videos/{video.id}/thumbnail", json={"timestamp_seconds": 12.5})
    assert response.status_code == 202
    assert response.json()["status"] == "pending"

    asset = (
        await db_session.execute(
            select(VideoAsset).where(VideoAsset.video_id == video.id, VideoAsset.asset_type == "thumbnail")
        )
    ).scalar_one()
    assert asset.status == "pending"
    assert asset.generation_mode == "manual"
    assert asset.metadata_json == {"timestamp_seconds": 12.5}


@pytest.mark.anyio
async def test_manual_thumbnail_request_replaces_a_pending_automatic_request(db_session, client):
    now = datetime.now(timezone.utc)
    video = Video(
        id=uuid.uuid4(),
        file_path="/media/example.mp4",
        title="Example",
        file_size=1024,
        file_mtime=now,
        status="ready",
        added_at=now,
        last_seen_at=now,
    )
    asset = VideoAsset(
        video_id=video.id,
        asset_type="thumbnail",
        relative_path=f"thumbnails/{video.id}.jpg",
        status="pending",
        generation_mode="automatic",
    )
    db_session.add_all([video, asset])
    await db_session.commit()

    response = await client.post(f"/api/v1/videos/{video.id}/thumbnail", json={"timestamp_seconds": 8})
    assert response.status_code == 202
    assert response.json()["status"] == "pending"

    await db_session.refresh(asset)
    assert asset.generation_mode == "manual"
    assert asset.metadata_json == {"timestamp_seconds": 8.0}


@pytest.mark.anyio
async def test_manual_thumbnail_request_rejects_timestamp_past_known_duration(db_session, client):
    now = datetime.now(timezone.utc)
    video = Video(
        id=uuid.uuid4(),
        file_path="/media/example.mp4",
        title="Example",
        file_size=1024,
        file_mtime=now,
        status="ready",
        added_at=now,
        last_seen_at=now,
    )
    db_session.add_all([video, VideoProbe(video_id=video.id, duration_seconds=10.0)])
    await db_session.commit()

    response = await client.post(f"/api/v1/videos/{video.id}/thumbnail", json={"timestamp_seconds": 10.1})
    assert response.status_code == 422
    assert "exceeds the known video duration" in response.json()["detail"]
    asset = (
        await db_session.execute(select(VideoAsset).where(VideoAsset.video_id == video.id))
    ).scalar_one_or_none()
    assert asset is None


@pytest.mark.anyio
async def test_thumbnail_request_has_explicit_missing_unavailable_and_generating_results(db_session, client):
    missing = await client.post(f"/api/v1/videos/{uuid.uuid4()}/thumbnail", json={"timestamp_seconds": 0})
    assert missing.status_code == 404

    now = datetime.now(timezone.utc)
    unavailable_video = Video(
        id=uuid.uuid4(),
        file_path="/media/unavailable.mp4",
        title="Unavailable",
        file_size=1024,
        file_mtime=now,
        status="unavailable",
        added_at=now,
        last_seen_at=now,
    )
    generating_video = Video(
        id=uuid.uuid4(),
        file_path="/media/generating.mp4",
        title="Generating",
        file_size=1024,
        file_mtime=now,
        status="ready",
        added_at=now,
        last_seen_at=now,
    )
    generating_asset = VideoAsset(
        video_id=generating_video.id,
        asset_type="thumbnail",
        relative_path=f"thumbnails/{generating_video.id}.jpg",
        status="generating",
    )
    db_session.add_all([unavailable_video, generating_video, generating_asset])
    await db_session.commit()

    unavailable = await client.post(
        f"/api/v1/videos/{unavailable_video.id}/thumbnail", json={"timestamp_seconds": 0}
    )
    assert unavailable.status_code == 409

    generating = await client.post(
        f"/api/v1/videos/{generating_video.id}/thumbnail", json={"timestamp_seconds": 0}
    )
    assert generating.status_code == 202
    assert generating.json() == {"status": "generating", "queued": False}


@pytest.mark.anyio
async def test_served_thumbnail_must_revalidate_after_replacement(db_session, client, monkeypatch, tmp_path):
    now = datetime.now(timezone.utc)
    video = Video(
        id=uuid.uuid4(),
        file_path="/media/example.mp4",
        title="Example",
        file_size=1024,
        file_mtime=now,
        status="ready",
        added_at=now,
        last_seen_at=now,
    )
    asset = VideoAsset(
        video_id=video.id,
        asset_type="thumbnail",
        relative_path=f"thumbnails/{video.id}.jpg",
        status="ready",
    )
    thumbnail = tmp_path / "thumbnail.jpg"
    thumbnail.write_bytes(b"jpeg")
    monkeypatch.setattr(AssetService, "resolve_relative_path", staticmethod(lambda _: thumbnail))
    db_session.add_all([video, asset])
    await db_session.commit()

    response = await client.get(f"/api/v1/assets/thumbnails/{video.id}")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "public, max-age=0, must-revalidate"
