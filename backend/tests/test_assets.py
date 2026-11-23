import asyncio
import sys
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.models.video import Video
from app.models.video_asset import VideoAsset
from app.models.video_probe import VideoProbe
from app.services.asset_service import AssetService, SEEKBAR_PREVIEW


def test_preview_vtt_timestamp_and_multi_sheet_cues():
    video_id = uuid.uuid4()
    assert AssetService.format_vtt_timestamp(3661.25) == "01:01:01.250"
    vtt = AssetService.build_preview_cues(video_id, 115, 12, 10, 10, 160, 90)
    assert vtt.startswith("WEBVTT\n\n")
    assert "00:00:00.000 --> 00:00:10.000\n/api/v1/assets/previews/" + str(video_id) + "/sprites/0#xywh=0,0,160,90" in vtt
    assert "/sprites/1#xywh=0,0,160,90" in vtt
    assert "00:01:50.000 --> 00:01:55.000" in vtt
    assert "00:01:55.000 -->" not in vtt


def test_preview_cue_builder_rejects_invalid_duration():
    with pytest.raises(ValueError):
        AssetService.build_preview_cues(uuid.uuid4(), 0, 1, 10, 100, 160, 90)


@pytest.mark.parametrize(
    ("configured_columns", "configured_frames", "expected"),
    [
        (150, 500, (100, 100)),
        (10, 500, (10, 100)),
        (10, 50, (10, 50)),
        (-2, 0, (1, 1)),
    ],
)
def test_preview_layout_enforces_hard_100_frame_limit(configured_columns, configured_frames, expected):
    assert AssetService.preview_layout(configured_columns, configured_frames) == expected


@pytest.mark.anyio
async def test_ffmpeg_process_is_reaped_after_communicate_timeout():
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        "import time; time.sleep(30)",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(process.communicate(), timeout=0.05)

    await AssetService._cleanup_ffmpeg_process(process)

    assert process.returncode is not None


def _ready_video(video_id, now):
    return Video(
        id=video_id,
        file_path=f"/media/{video_id}.mp4",
        title="Preview recovery",
        file_size=123,
        file_mtime=now,
        status="ready",
        added_at=now,
        last_seen_at=now,
    )


@pytest.mark.anyio
async def test_preview_request_requeues_when_vtt_is_missing_but_sprite_remains(
    db_session, monkeypatch, tmp_path
):
    now = datetime.now(timezone.utc)
    video_id = uuid.uuid4()
    video = _ready_video(video_id, now)
    vtt_relative = AssetService.seekbar_vtt_path(video_id)
    sprite_relative = AssetService.seekbar_sprite_path(video_id, 0)
    sprite = tmp_path / sprite_relative
    sprite.parent.mkdir(parents=True, exist_ok=True)
    sprite.write_bytes(b"jpeg")
    monkeypatch.setattr(
        "app.services.asset_service.get_settings",
        lambda: SimpleNamespace(assets_path=str(tmp_path)),
    )
    asset = VideoAsset(
        video_id=video_id,
        asset_type=SEEKBAR_PREVIEW,
        relative_path=vtt_relative,
        status="ready",
        source_file_mtime=now,
        source_file_size=video.file_size,
        metadata_json={"sheets": [sprite_relative]},
    )
    db_session.add_all([video, asset])
    await db_session.commit()

    assert await AssetService.request_seekbar_preview(video_id) is True
    await db_session.refresh(asset)
    assert asset.status == "pending"


@pytest.mark.anyio
async def test_startup_preview_recovery_requeues_missing_vtt_with_remaining_sprite(
    db_session, monkeypatch, tmp_path
):
    now = datetime.now(timezone.utc)
    video_id = uuid.uuid4()
    video = _ready_video(video_id, now)
    vtt_relative = AssetService.seekbar_vtt_path(video_id)
    sprite_relative = AssetService.seekbar_sprite_path(video_id, 0)
    sprite = tmp_path / sprite_relative
    sprite.parent.mkdir(parents=True, exist_ok=True)
    sprite.write_bytes(b"jpeg")
    monkeypatch.setattr(
        "app.services.asset_service.get_settings",
        lambda: SimpleNamespace(assets_path=str(tmp_path)),
    )
    asset = VideoAsset(
        video_id=video_id,
        asset_type=SEEKBAR_PREVIEW,
        relative_path=vtt_relative,
        status="ready",
        source_file_mtime=now,
        source_file_size=video.file_size,
        metadata_json={"sheets": [sprite_relative]},
    )
    db_session.add_all([video, asset])
    await db_session.commit()

    queued = await AssetService.mark_stale_previews_pending()

    assert video_id in queued
    await db_session.refresh(asset)
    assert asset.status == "pending"


@pytest.mark.anyio
async def test_malformed_preview_metadata_does_not_stop_startup_recovery(
    db_session, monkeypatch, tmp_path
):
    now = datetime.now(timezone.utc)
    malformed_id, eligible_id = uuid.uuid4(), uuid.uuid4()
    malformed_video = _ready_video(malformed_id, now)
    eligible_video = _ready_video(eligible_id, now)
    malformed_asset = VideoAsset(
        video_id=malformed_id,
        asset_type=SEEKBAR_PREVIEW,
        relative_path="../outside.vtt",
        status="ready",
        source_file_mtime=now,
        source_file_size=malformed_video.file_size,
        metadata_json={"sheets": "not-a-list"},
    )
    monkeypatch.setattr(
        "app.services.asset_service.get_settings",
        lambda: SimpleNamespace(assets_path=str(tmp_path)),
    )
    db_session.add_all([malformed_video, eligible_video, malformed_asset])
    await db_session.commit()

    queued = await AssetService.mark_stale_previews_pending()

    assert malformed_id in queued
    assert eligible_id in queued


@pytest.mark.anyio
async def test_preview_routes_serve_vtt_and_validate_sprite_index(db_session, client, monkeypatch, tmp_path):
    now = datetime.now(timezone.utc)
    video = Video(id=uuid.uuid4(), file_path="/media/preview.mp4", title="Preview", file_size=12,
                  file_mtime=now, status="ready", added_at=now, last_seen_at=now)
    vtt = tmp_path / "preview.vtt"
    sprite = tmp_path / "sprite.jpg"
    vtt.write_text("WEBVTT\n", encoding="utf-8")
    sprite.write_bytes(b"jpeg")
    asset = VideoAsset(video_id=video.id, asset_type=SEEKBAR_PREVIEW,
                       relative_path=f"previews/{video.id}.vtt", status="ready",
                       metadata_json={"sheets": [f"previews/{video.id}-0000.jpg"]})
    db_session.add_all([video, asset])
    await db_session.commit()
    monkeypatch.setattr(AssetService, "resolve_relative_path", staticmethod(lambda path: vtt if path.endswith(".vtt") else sprite))

    response = await client.get(f"/api/v1/assets/previews/{video.id}/metadata")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/vtt")
    assert response.headers["cache-control"] == "public, max-age=0, must-revalidate"
    valid_sprite = await client.get(f"/api/v1/assets/previews/{video.id}/sprites/0")
    assert valid_sprite.status_code == 200
    assert valid_sprite.headers["content-type"].startswith("image/jpeg")
    assert (await client.get(f"/api/v1/assets/previews/{video.id}/sprites/-1")).status_code == 404
    assert (await client.get(f"/api/v1/assets/previews/{video.id}/sprites/1")).status_code == 404


@pytest.mark.parametrize(
    "metadata_json",
    [
        [],
        "unexpected metadata shape",
        {"sheets": "not-a-list"},
        {"sheets": None},
        {"sheets": [None]},
        {"sheets": [""]},
        {"sheets": ["../outside.jpg"]},
        {"sheets": ["previews/missing.jpg"]},
    ],
)
@pytest.mark.anyio
async def test_sprite_route_returns_not_found_for_malformed_or_unavailable_metadata(
    db_session, client, monkeypatch, tmp_path, metadata_json
):
    now = datetime.now(timezone.utc)
    video_id = uuid.uuid4()
    video = _ready_video(video_id, now)
    asset = VideoAsset(
        video_id=video_id,
        asset_type=SEEKBAR_PREVIEW,
        relative_path=AssetService.seekbar_vtt_path(video_id),
        status="ready",
        metadata_json=metadata_json,
    )
    monkeypatch.setattr(
        "app.services.asset_service.get_settings",
        lambda: SimpleNamespace(assets_path=str(tmp_path)),
    )
    db_session.add_all([video, asset])
    await db_session.commit()

    response = await client.get(f"/api/v1/assets/previews/{video_id}/sprites/0")

    assert response.status_code == 404
    assert response.json() == {"detail": "Seekbar preview sprite not found."}


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
