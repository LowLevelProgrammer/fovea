import asyncio
import logging
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path, PurePosixPath
from uuid import UUID

from sqlalchemy import select

from app.core.config import get_settings
from app.db.session import async_session
from app.models.video import Video
from app.models.video_asset import VideoAsset
from app.models.video_probe import VideoProbe

logger = logging.getLogger(__name__)

THUMBNAIL = "thumbnail"


class ThumbnailRequestResult(StrEnum):
    QUEUED = "queued"
    PENDING = "pending"
    GENERATING = "generating"
    NOT_FOUND = "not_found"
    UNAVAILABLE = "unavailable"
    INVALID_TIMESTAMP = "invalid_timestamp"


class AssetService:
    """Creates and tracks generated media assets without touching source files."""

    @staticmethod
    def thumbnail_path(video_id: UUID) -> str:
        return f"thumbnails/{video_id}.jpg"

    @staticmethod
    def resolve_relative_path(relative_path: str) -> Path:
        root = Path(get_settings().assets_path).resolve()
        resolved = (root / PurePosixPath(relative_path)).resolve()
        if root not in resolved.parents and resolved != root:
            raise ValueError("Invalid asset path")
        return resolved

    @staticmethod
    def _is_stale(asset: VideoAsset, video: Video) -> bool:
        if asset.status != "ready":
            return True
        if asset.source_file_mtime != video.file_mtime or asset.source_file_size != video.file_size:
            return True
        return not AssetService.resolve_relative_path(asset.relative_path).is_file()

    @staticmethod
    async def request_thumbnail(
        video_id: UUID,
        timestamp_seconds: float | None = None,
        force_automatic: bool = False,
    ) -> ThumbnailRequestResult:
        """Request thumbnail work without conflating missing and in-progress videos."""
        mode = "manual" if timestamp_seconds is not None else "automatic"
        async with async_session() as session:
            video = await session.get(Video, video_id)
            if video is None:
                return ThumbnailRequestResult.NOT_FOUND
            if video.status == "unavailable":
                return ThumbnailRequestResult.UNAVAILABLE
            if timestamp_seconds is not None:
                probe = await session.get(VideoProbe, video_id)
                if probe is not None and probe.duration_seconds is not None and timestamp_seconds > probe.duration_seconds:
                    return ThumbnailRequestResult.INVALID_TIMESTAMP
            asset = (
                await session.execute(
                    select(VideoAsset).where(
                        VideoAsset.video_id == video_id, VideoAsset.asset_type == THUMBNAIL
                    )
                )
            ).scalar_one_or_none()
            created = asset is None
            if asset is None:
                asset = VideoAsset(
                    video_id=video_id,
                    asset_type=THUMBNAIL,
                    relative_path=AssetService.thumbnail_path(video_id),
                )
                session.add(asset)
            stale = AssetService._is_stale(asset, video)
            if not created and asset.status == "generating":
                return ThumbnailRequestResult.GENERATING
            if not created and asset.status == "pending" and mode == "automatic" and not force_automatic:
                return ThumbnailRequestResult.PENDING
            if mode == "automatic" and asset.generation_mode == "manual" and not stale and not force_automatic:
                return ThumbnailRequestResult.PENDING
            if mode == "automatic" and not stale and not force_automatic:
                return ThumbnailRequestResult.PENDING

            asset.status = "pending"
            asset.generation_mode = mode
            asset.error_message = None
            asset.metadata_json = {"timestamp_seconds": timestamp_seconds} if timestamp_seconds is not None else None
            await session.commit()
            return ThumbnailRequestResult.QUEUED

    @staticmethod
    async def mark_stale_thumbnails_pending() -> list[UUID]:
        """Recover missing/stale assets at startup with two bounded database queries."""
        async with async_session() as session:
            videos = (await session.execute(select(Video).where(Video.status == "ready"))).scalars().all()
            assets = (
                await session.execute(select(VideoAsset).where(VideoAsset.asset_type == THUMBNAIL))
            ).scalars().all()
            assets_by_video = {asset.video_id: asset for asset in assets}
            queued: list[UUID] = []
            for video in videos:
                asset = assets_by_video.get(video.id)
                if asset is None:
                    asset = VideoAsset(
                        video_id=video.id,
                        asset_type=THUMBNAIL,
                        relative_path=AssetService.thumbnail_path(video.id),
                        status="pending",
                    )
                    session.add(asset)
                    queued.append(video.id)
                elif AssetService._is_stale(asset, video):
                    source_changed = (
                        asset.source_file_mtime != video.file_mtime
                        or asset.source_file_size != video.file_size
                    )
                    asset.status = "pending"
                    if source_changed:
                        asset.generation_mode = "automatic"
                        asset.metadata_json = None
                    asset.error_message = None
                    queued.append(video.id)
            await session.commit()
            return queued

    @staticmethod
    async def generate_thumbnail(video_id: UUID) -> None:
        async with async_session() as session:
            video = await session.get(Video, video_id)
            asset = (
                await session.execute(
                    select(VideoAsset).where(
                        VideoAsset.video_id == video_id, VideoAsset.asset_type == THUMBNAIL
                    )
                )
            ).scalar_one_or_none()
            if video is None or asset is None:
                return
            asset.status = "generating"
            await session.commit()

            probe = await session.get(VideoProbe, video_id)
            timestamp = (asset.metadata_json or {}).get("timestamp_seconds")
            if timestamp is None:
                timestamp = (probe.duration_seconds * 0.1) if probe and probe.duration_seconds else 0.0
            source_path = Path(video.file_path)
            output_path = AssetService.resolve_relative_path(asset.relative_path)

        temporary_path: Path | None = None
        process: asyncio.subprocess.Process | None = None
        try:
            if not source_path.is_file():
                raise FileNotFoundError(f"Video source missing: {source_path}")
            output_path.parent.mkdir(parents=True, exist_ok=True)
            temporary_path = output_path.with_name(f"{output_path.stem}.tmp.jpg")
            command = [
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-ss", str(max(0.0, timestamp)),
                "-i", str(source_path), "-frames:v", "1", "-vf", f"scale={get_settings().thumbnail_width}:-2",
                "-q:v", "3", "-y", str(temporary_path),
            ]
            process = await asyncio.create_subprocess_exec(
                *command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            _, stderr = await asyncio.wait_for(process.communicate(), timeout=90)
            if process.returncode != 0 or not temporary_path.is_file():
                raise RuntimeError(stderr.decode("utf-8", errors="replace").strip() or "FFmpeg failed")
            temporary_path.replace(output_path)
            await AssetService._record_thumbnail_success(video_id, timestamp)
        except asyncio.CancelledError:
            if process is not None and process.returncode is None:
                process.kill()
                await process.wait()
            raise
        except TimeoutError as exc:
            if process is not None and process.returncode is None:
                process.kill()
                await process.wait()
            message = f"FFmpeg timed out after 90 seconds: {exc}"
            logger.error("Thumbnail generation failed for video %s: %s", video_id, message)
            await AssetService._record_thumbnail_failure(video_id, message)
        except Exception as exc:
            logger.exception("Thumbnail generation failed for video %s", video_id)
            await AssetService._record_thumbnail_failure(video_id, str(exc))
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)

    @staticmethod
    async def _record_thumbnail_success(video_id: UUID, timestamp: float) -> None:
        async with async_session() as session:
            video = await session.get(Video, video_id)
            asset = (
                await session.execute(select(VideoAsset).where(VideoAsset.video_id == video_id, VideoAsset.asset_type == THUMBNAIL))
            ).scalar_one()
            asset.status = "ready"
            asset.generated_at = datetime.now(timezone.utc)
            asset.source_file_mtime = video.file_mtime
            asset.source_file_size = video.file_size
            asset.error_message = None
            asset.metadata_json = {"timestamp_seconds": timestamp}
            await session.commit()

    @staticmethod
    async def _record_thumbnail_failure(video_id: UUID, message: str) -> None:
        async with async_session() as session:
            asset = (
                await session.execute(select(VideoAsset).where(VideoAsset.video_id == video_id, VideoAsset.asset_type == THUMBNAIL))
            ).scalar_one_or_none()
            if asset is not None:
                asset.status = "failed"
                asset.error_message = message[:1000]
                await session.commit()

    @staticmethod
    async def generate_asset(video_id: UUID, asset_type: str) -> None:
        if asset_type != THUMBNAIL:
            raise ValueError(f"Unsupported asset type: {asset_type}")
        await AssetService.generate_thumbnail(video_id)
