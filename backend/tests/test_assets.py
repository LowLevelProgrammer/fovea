import asyncio
import os
import sys
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.models.video import Video
from app.models.video_asset import VideoAsset
from app.models.video_probe import VideoProbe
from app.models.watch_path import WatchPath
from app.services.asset_service import AssetService, HOVER_PREVIEW, SEEKBAR_PREVIEW, THUMBNAIL
from app.services.scan_service import ScanService
from app.core.config import Settings


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


def test_hover_tile_defaults_are_independent_from_seekbar_tiles():
    settings = Settings()
    assert (settings.preview_tile_width, settings.preview_tile_height) == (160, 90)
    assert (settings.hover_preview_tile_width, settings.hover_preview_tile_height) == (320, 180)


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


def _hover_test_settings(asset_root):
    return SimpleNamespace(
        assets_path=str(asset_root),
        preview_tile_width=160,
        preview_tile_height=90,
        preview_sprite_columns=10,
        preview_sprite_max_frames=100,
        hover_preview_tile_width=320,
        hover_preview_tile_height=180,
    )


@pytest.mark.anyio
async def test_hover_preview_generation_writes_one_30_frame_sprite_and_cleans_temp(
    db_session, monkeypatch, tmp_path
):
    now = datetime.now(timezone.utc)
    video_id = uuid.uuid4()
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source video")
    stat = source.stat()
    video = _ready_video(video_id, datetime.fromtimestamp(stat.st_mtime, timezone.utc))
    video.file_path = str(source)
    video.file_size = stat.st_size
    asset = VideoAsset(
        video_id=video_id,
        asset_type=HOVER_PREVIEW,
        relative_path=AssetService.hover_preview_sprite_path(video_id),
        status="pending",
    )
    probe = VideoProbe(video_id=video_id, duration_seconds=60, video_codec="h264")
    assets_root = tmp_path / "assets"
    commands = []

    class FakeProcess:
        returncode = 0

        async def communicate(self):
            return b"", b""

    async def fake_ffmpeg(*command, **_kwargs):
        commands.append(command)
        from pathlib import Path

        Path(command[-1]).write_bytes(b"sprite jpeg")
        return FakeProcess()

    monkeypatch.setattr("app.services.asset_service.get_settings", lambda: _hover_test_settings(assets_root))
    monkeypatch.setattr("app.services.asset_service.asyncio.create_subprocess_exec", fake_ffmpeg)
    db_session.add_all([video, asset, probe])
    await db_session.commit()

    await AssetService.generate_hover_preview(video_id)

    await db_session.refresh(asset)
    expected_path = AssetService.hover_preview_sprite_path(video_id)
    metadata = asset.metadata_json
    assert asset.status == "ready"
    assert asset.relative_path == expected_path
    assert asset.source_file_size == stat.st_size
    assert asset.source_file_mtime == video.file_mtime
    assert metadata["sheets"] == [expected_path]
    assert metadata["frame_count"] == 30
    assert metadata["duration_seconds"] == 5.0
    assert metadata["columns"] == 10 and metadata["rows"] == 3
    assert metadata["tile_width"] == 320 and metadata["tile_height"] == 180
    assert metadata["rows"] == 3
    hover_filter = commands[0][commands[0].index("-vf") + 1]
    assert "fps=6.000000" in hover_filter
    assert "scale=320:180:force_original_aspect_ratio=decrease" in hover_filter
    assert "pad=320:180:(ow-iw)/2:(oh-ih)/2" in hover_filter
    assert "tile=10x3:nb_frames=30" in hover_filter
    assert AssetService.resolve_relative_path(expected_path).read_bytes() == b"sprite jpeg"
    assert not list(assets_root.glob(".fovea-hover-*"))


@pytest.mark.anyio
async def test_seekbar_generation_keeps_160_by_90_tiles(db_session, monkeypatch, tmp_path):
    video_id = uuid.uuid4()
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source video")
    stat = source.stat()
    now = datetime.fromtimestamp(stat.st_mtime, timezone.utc)
    video = _ready_video(video_id, now)
    video.file_path = str(source)
    video.file_size = stat.st_size
    asset = VideoAsset(
        video_id=video_id,
        asset_type=SEEKBAR_PREVIEW,
        relative_path=AssetService.seekbar_vtt_path(video_id),
        status="pending",
    )
    probe = VideoProbe(video_id=video_id, duration_seconds=10, video_codec="h264")
    assets_root = tmp_path / "assets"
    commands = []

    class FakeProcess:
        returncode = 0

        async def communicate(self):
            command = commands[-1]
            destination = command[-1]
            if "%08d" in destination:
                from pathlib import Path

                Path(destination.replace("%08d", "00000001")).write_bytes(b"frame")
            else:
                from pathlib import Path

                Path(destination).write_bytes(b"seekbar sprite")
            return b"", b""

    async def fake_ffmpeg(*command, **_kwargs):
        commands.append(command)
        return FakeProcess()

    monkeypatch.setattr("app.services.asset_service.get_settings", lambda: _hover_test_settings(assets_root))
    monkeypatch.setattr("app.services.asset_service.asyncio.create_subprocess_exec", fake_ffmpeg)
    db_session.add_all([video, asset, probe])
    await db_session.commit()

    await AssetService.generate_seekbar_preview(video_id)

    await db_session.refresh(asset)
    assert asset.status == "ready"
    assert asset.metadata_json["tile_width"] == 160
    assert asset.metadata_json["tile_height"] == 90
    first_filter = commands[0][commands[0].index("-vf") + 1]
    assert "scale=160:90:force_original_aspect_ratio=decrease" in first_filter
    assert "pad=160:90:(ow-iw)/2:(oh-ih)/2" in first_filter


@pytest.mark.anyio
async def test_hover_preview_source_change_during_ffmpeg_fails_and_cleans_output(
    db_session, monkeypatch, tmp_path
):
    now = datetime.now(timezone.utc)
    video_id = uuid.uuid4()
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source video")
    stat = source.stat()
    video = _ready_video(video_id, datetime.fromtimestamp(stat.st_mtime, timezone.utc))
    video.file_path = str(source)
    video.file_size = stat.st_size
    asset = VideoAsset(
        video_id=video_id,
        asset_type=HOVER_PREVIEW,
        relative_path=AssetService.hover_preview_sprite_path(video_id),
        status="pending",
    )
    probe = VideoProbe(video_id=video_id, duration_seconds=60, video_codec="h264")
    assets_root = tmp_path / "assets"

    class FakeProcess:
        returncode = 0

        async def communicate(self):
            source.write_bytes(source.read_bytes() + b" changed")
            return b"", b""

    async def fake_ffmpeg(*command, **_kwargs):
        from pathlib import Path

        Path(command[-1]).write_bytes(b"obsolete sprite")
        return FakeProcess()

    monkeypatch.setattr("app.services.asset_service.get_settings", lambda: _hover_test_settings(assets_root))
    monkeypatch.setattr("app.services.asset_service.asyncio.create_subprocess_exec", fake_ffmpeg)
    db_session.add_all([video, asset, probe])
    await db_session.commit()

    await AssetService.generate_hover_preview(video_id)

    await db_session.refresh(asset)
    assert asset.status == "failed"
    assert not AssetService.resolve_relative_path(AssetService.hover_preview_sprite_path(video_id)).exists()
    assert not list(assets_root.glob(".fovea-hover-*"))


@pytest.mark.parametrize("failure", ["ffmpeg", "missing_source"])
@pytest.mark.anyio
async def test_hover_preview_generation_failures_mark_asset_failed_and_clean_temp(
    db_session, monkeypatch, tmp_path, failure
):
    now = datetime.now(timezone.utc)
    video_id = uuid.uuid4()
    source = tmp_path / "source.mp4"
    if failure == "ffmpeg":
        source.write_bytes(b"source video")
        stat = source.stat()
        source_size = stat.st_size
        source_mtime = datetime.fromtimestamp(stat.st_mtime, timezone.utc)
    else:
        source_size = 0
        source_mtime = now
    video = _ready_video(video_id, source_mtime)
    video.file_path = str(source)
    video.file_size = source_size
    asset = VideoAsset(
        video_id=video_id,
        asset_type=HOVER_PREVIEW,
        relative_path=AssetService.hover_preview_sprite_path(video_id),
        status="pending",
    )
    probe = VideoProbe(video_id=video_id, duration_seconds=10, video_codec="h264")
    assets_root = tmp_path / "assets"

    class FailedProcess:
        returncode = 1

        async def communicate(self):
            return b"", b"expected test ffmpeg failure"

    async def fail_ffmpeg(*_command, **_kwargs):
        return FailedProcess()

    monkeypatch.setattr("app.services.asset_service.get_settings", lambda: _hover_test_settings(assets_root))
    monkeypatch.setattr("app.services.asset_service.asyncio.create_subprocess_exec", fail_ffmpeg)
    db_session.add_all([video, asset, probe])
    await db_session.commit()

    await AssetService.generate_hover_preview(video_id)

    await db_session.refresh(asset)
    assert asset.status == "failed"
    assert asset.error_message
    assert not list(assets_root.glob(".fovea-hover-*"))
    assert not AssetService.resolve_relative_path(AssetService.hover_preview_sprite_path(video_id)).exists()


@pytest.mark.anyio
async def test_hover_preview_startup_recovery_queues_missing_but_keeps_current_asset(
    db_session, monkeypatch, tmp_path
):
    now = datetime.now(timezone.utc)
    current_id, missing_id = uuid.uuid4(), uuid.uuid4()
    current_video, missing_video = _ready_video(current_id, now), _ready_video(missing_id, now)
    assets_root = tmp_path / "assets"
    current_path = assets_root / AssetService.hover_preview_sprite_path(current_id)
    current_path.parent.mkdir(parents=True, exist_ok=True)
    current_path.write_bytes(b"sprite")
    settings = _hover_test_settings(assets_root)
    monkeypatch.setattr("app.services.asset_service.get_settings", lambda: settings)
    current_asset = VideoAsset(
        video_id=current_id,
        asset_type=HOVER_PREVIEW,
        relative_path=AssetService.hover_preview_sprite_path(current_id),
        status="ready",
        source_file_size=current_video.file_size,
        source_file_mtime=current_video.file_mtime,
        metadata_json={
            "sheets": [AssetService.hover_preview_sprite_path(current_id)],
            "frame_count": 30,
            "duration_seconds": 5.0,
            "columns": 10,
            "tile_width": 320,
            "tile_height": 180,
            "rows": 3,
        },
    )
    missing_asset = VideoAsset(
        video_id=missing_id,
        asset_type=HOVER_PREVIEW,
        relative_path=AssetService.hover_preview_sprite_path(missing_id),
        status="ready",
        source_file_size=missing_video.file_size,
        source_file_mtime=missing_video.file_mtime,
        metadata_json={
            "sheets": [AssetService.hover_preview_sprite_path(missing_id)],
            "frame_count": 30,
            "duration_seconds": 5.0,
            "columns": 10,
            "tile_width": 160,
            "tile_height": 90,
            "rows": 3,
        },
    )
    db_session.add_all([current_video, missing_video, current_asset, missing_asset])
    await db_session.commit()

    queued = await AssetService.mark_stale_hover_previews_pending()

    assert queued == [missing_id]
    await db_session.refresh(current_asset)
    await db_session.refresh(missing_asset)
    assert current_asset.status == "ready"
    assert missing_asset.status == "pending"


@pytest.mark.anyio
async def test_hover_preview_request_queues_old_160_by_90_sprite(db_session, monkeypatch, tmp_path):
    video_id = uuid.uuid4()
    now = datetime.now(timezone.utc)
    video = _ready_video(video_id, now)
    sprite_relative = AssetService.hover_preview_sprite_path(video_id)
    sprite = tmp_path / sprite_relative
    sprite.parent.mkdir(parents=True, exist_ok=True)
    sprite.write_bytes(b"old 160x90 sprite")
    old_asset = VideoAsset(
        video_id=video_id,
        asset_type=HOVER_PREVIEW,
        relative_path=sprite_relative,
        status="ready",
        source_file_size=video.file_size,
        source_file_mtime=video.file_mtime,
        metadata_json={
            "sheets": [sprite_relative],
            "frame_count": 30,
            "duration_seconds": 5.0,
            "columns": 10,
            "rows": 3,
            "tile_width": 160,
            "tile_height": 90,
        },
    )
    monkeypatch.setattr(
        "app.services.asset_service.get_settings",
        lambda: _hover_test_settings(tmp_path),
    )
    db_session.add_all([video, old_asset])
    await db_session.commit()

    assert await AssetService.request_hover_preview(video_id) is True
    await db_session.refresh(old_asset)
    assert old_asset.status == "pending"


@pytest.mark.anyio
async def test_source_signature_scan_invalidates_all_asset_types_only_after_change(db_session, tmp_path):
    source = tmp_path / "video.mp4"
    source.write_bytes(b"original source")
    original_stat = source.stat()
    original_mtime = datetime.fromtimestamp(original_stat.st_mtime, timezone.utc)
    now = datetime.now(timezone.utc)
    video_id = uuid.uuid4()
    video = Video(
        id=video_id,
        file_path=str(source),
        title="Changed source",
        file_size=original_stat.st_size,
        file_mtime=original_mtime,
        fingerprint=f"{original_stat.st_size}:{original_mtime.isoformat()}",
        status="ready",
        added_at=now,
        last_seen_at=now,
    )
    watch_path = WatchPath(
        id=uuid.uuid4(),
        path=str(tmp_path),
        label="Assets test",
        scan_recursive=True,
        enabled=True,
    )
    assets = [
        VideoAsset(video_id=video_id, asset_type=THUMBNAIL, relative_path=AssetService.thumbnail_path(video_id), status="ready"),
        VideoAsset(video_id=video_id, asset_type=SEEKBAR_PREVIEW, relative_path=AssetService.seekbar_vtt_path(video_id), status="ready"),
        VideoAsset(video_id=video_id, asset_type=HOVER_PREVIEW, relative_path=AssetService.hover_preview_sprite_path(video_id), status="ready"),
    ]
    db_session.add_all([video, watch_path, *assets])
    await db_session.commit()

    await ScanService.scan(watch_path.id)
    for asset in assets:
        await db_session.refresh(asset)
        assert asset.status == "ready"

    source.write_bytes(b"changed source size")
    changed_mtime = original_stat.st_mtime + 2
    os.utime(source, (changed_mtime, changed_mtime))
    await ScanService.scan(watch_path.id)

    for asset in assets:
        await db_session.refresh(asset)
        assert asset.status == "stale"


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
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")
    stat = source.stat()
    now = datetime.fromtimestamp(stat.st_mtime, timezone.utc)
    video = Video(id=uuid.uuid4(), file_path=str(source), title="Preview", file_size=stat.st_size,
                  file_mtime=now, status="ready", added_at=now, last_seen_at=now)
    vtt = tmp_path / "preview.vtt"
    sprite = tmp_path / "sprite.jpg"
    vtt.write_text("WEBVTT\n", encoding="utf-8")
    sprite.write_bytes(b"jpeg")
    asset = VideoAsset(video_id=video.id, asset_type=SEEKBAR_PREVIEW,
                       relative_path=f"previews/{video.id}.vtt", status="ready",
                       source_file_mtime=video.file_mtime, source_file_size=video.file_size,
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
    source = tmp_path / f"{video_id}.mp4"
    source.write_bytes(b"source")
    stat = source.stat()
    video.file_path = str(source)
    video.file_size = stat.st_size
    video.file_mtime = datetime.fromtimestamp(stat.st_mtime, timezone.utc)
    asset = VideoAsset(
        video_id=video_id,
        asset_type=SEEKBAR_PREVIEW,
        relative_path=AssetService.seekbar_vtt_path(video_id),
        status="ready",
        source_file_mtime=video.file_mtime,
        source_file_size=video.file_size,
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
async def test_hover_sprite_route_serves_tracked_current_sprite_and_rejects_stale_source(
    db_session, client, monkeypatch, tmp_path
):
    source = tmp_path / "video.mp4"
    source.write_bytes(b"source")
    stat = source.stat()
    now = datetime.fromtimestamp(stat.st_mtime, timezone.utc)
    video_id = uuid.uuid4()
    video = _ready_video(video_id, now)
    video.file_path = str(source)
    video.file_size = stat.st_size
    sprite_relative = AssetService.hover_preview_sprite_path(video_id)
    sprite = tmp_path / "assets" / sprite_relative
    sprite.parent.mkdir(parents=True, exist_ok=True)
    sprite.write_bytes(b"sprite jpg")
    asset = VideoAsset(
        video_id=video_id,
        asset_type=HOVER_PREVIEW,
        relative_path=sprite_relative,
        status="ready",
        source_file_size=video.file_size,
        source_file_mtime=video.file_mtime,
        metadata_json={"sheets": [sprite_relative]},
    )
    monkeypatch.setattr(
        "app.services.asset_service.get_settings",
        lambda: SimpleNamespace(assets_path=str(tmp_path / "assets")),
    )
    db_session.add_all([video, asset])
    await db_session.commit()

    response = await client.get(f"/api/v1/assets/hover-previews/{video_id}")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/jpeg")
    assert response.headers["cache-control"] == "public, max-age=0, must-revalidate"
    assert response.content == b"sprite jpg"

    source.write_bytes(b"source changed")
    stale = await client.get(f"/api/v1/assets/hover-previews/{video_id}")
    assert stale.status_code == 404


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
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")
    stat = source.stat()
    video = Video(
        id=uuid.uuid4(),
        file_path=str(source),
        title="Example",
        file_size=stat.st_size,
        file_mtime=datetime.fromtimestamp(stat.st_mtime, timezone.utc),
        status="ready",
        added_at=now,
        last_seen_at=now,
    )
    asset = VideoAsset(
        video_id=video.id,
        asset_type="thumbnail",
        relative_path=f"thumbnails/{video.id}.jpg",
        status="ready",
        source_file_mtime=video.file_mtime,
        source_file_size=video.file_size,
    )
    thumbnail = tmp_path / "thumbnail.jpg"
    thumbnail.write_bytes(b"jpeg")
    monkeypatch.setattr(AssetService, "resolve_relative_path", staticmethod(lambda _: thumbnail))
    db_session.add_all([video, asset])
    await db_session.commit()

    response = await client.get(f"/api/v1/assets/thumbnails/{video.id}")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "public, max-age=0, must-revalidate"
