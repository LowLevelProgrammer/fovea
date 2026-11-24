import asyncio
import logging
import math
import shutil
import tempfile
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
SEEKBAR_PREVIEW = "seekbar_preview"
HOVER_PREVIEW = "hover_preview"
MAX_PREVIEW_FRAMES_PER_SHEET = 100
HOVER_PREVIEW_FRAME_COUNT = 30
HOVER_PREVIEW_DURATION_SECONDS = 5.0


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
    def seekbar_vtt_path(video_id: UUID) -> str:
        return f"previews/{video_id}.vtt"

    @staticmethod
    def seekbar_sprite_path(video_id: UUID, index: int) -> str:
        return f"previews/{video_id}-{index:04d}.jpg"

    @staticmethod
    def hover_preview_sprite_path(video_id: UUID) -> str:
        return f"hover/{video_id}.jpg"

    @staticmethod
    def format_vtt_timestamp(seconds: float) -> str:
        milliseconds = max(0, round(seconds * 1000))
        hours, remainder = divmod(milliseconds, 3_600_000)
        minutes, remainder = divmod(remainder, 60_000)
        whole_seconds, millis = divmod(remainder, 1000)
        return f"{hours:02d}:{minutes:02d}:{whole_seconds:02d}.{millis:03d}"

    @staticmethod
    def build_preview_cues(video_id: UUID, duration: float, frame_count: int, columns: int, max_frames: int, width: int, height: int) -> str:
        if duration <= 0 or frame_count <= 0 or columns <= 0 or max_frames <= 0 or width <= 0 or height <= 0:
            raise ValueError("Preview cues require positive duration, frame count, and columns")
        lines = ["WEBVTT", ""]
        for frame in range(frame_count):
            start = frame * 10.0
            end = min((frame + 1) * 10.0, duration)
            if start >= duration or end <= start:
                continue
            sheet, local_frame = divmod(frame, max_frames)
            x = (local_frame % columns) * width
            y = (local_frame // columns) * height
            lines.extend([
                f"{AssetService.format_vtt_timestamp(start)} --> {AssetService.format_vtt_timestamp(end)}",
                f"/api/v1/assets/previews/{video_id}/sprites/{sheet}#xywh={x},{y},{width},{height}",
                "",
            ])
        return "\n".join(lines)

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
    def preview_layout(configured_columns: int, configured_max_frames: int) -> tuple[int, int]:
        """Return a bounded sprite layout; no sheet may contain over 100 frames."""
        columns = min(MAX_PREVIEW_FRAMES_PER_SHEET, max(1, configured_columns))
        max_frames = min(MAX_PREVIEW_FRAMES_PER_SHEET, max(columns, configured_max_frames))
        return columns, max_frames

    @staticmethod
    def hover_layout() -> tuple[int, float, int]:
        return HOVER_PREVIEW_FRAME_COUNT, HOVER_PREVIEW_DURATION_SECONDS, 10

    @staticmethod
    async def _cleanup_ffmpeg_process(process: asyncio.subprocess.Process) -> None:
        """Stop and reap an FFmpeg process without masking the active failure."""
        if process.returncode is not None:
            return
        try:
            try:
                process.terminate()
            except ProcessLookupError:
                pass
        except BaseException:
            logger.exception("Failed to terminate FFmpeg subprocess; forcing kill")

        try:
            await asyncio.wait_for(process.communicate(), timeout=5)
            return
        except BaseException:
            # A timeout, cancellation, or pipe error can interrupt communicate.
            # Force termination and still wait for the child to be reaped.
            if process.returncode is None:
                try:
                    process.kill()
                except ProcessLookupError:
                    pass
                except BaseException:
                    logger.exception("Failed to kill FFmpeg subprocess")
            try:
                await asyncio.wait_for(process.communicate(), timeout=5)
            except BaseException:
                try:
                    await process.wait()
                except BaseException:
                    # Preserve the original timeout/cancellation/generation error.
                    logger.exception("Failed to reap FFmpeg subprocess")

    @staticmethod
    def _preview_files_complete(asset: VideoAsset, video: Video) -> bool:
        """Check the VTT and every referenced sheet, treating bad metadata as stale."""
        try:
            if asset.relative_path != AssetService.seekbar_vtt_path(video.id):
                raise ValueError("Unexpected seekbar metadata path")
            if AssetService._is_stale(asset, video):
                return False
            metadata = asset.metadata_json
            sheets = metadata.get("sheets") if isinstance(metadata, dict) else None
            if not isinstance(sheets, list) or not sheets or not all(
                isinstance(path, str) and path for path in sheets
            ):
                raise ValueError("Invalid seekbar sprite sheet metadata")
            return all(AssetService.resolve_relative_path(path).is_file() for path in sheets)
        except (OSError, TypeError, ValueError) as exc:
            logger.warning("Seekbar preview metadata is stale for video %s: %s", video.id, exc)
            return False

    @staticmethod
    def _hover_preview_file_complete(asset: VideoAsset, video: Video) -> bool:
        """Validate the single hover sprite and its source signature."""
        try:
            expected_path = AssetService.hover_preview_sprite_path(video.id)
            frame_count, duration, columns = AssetService.hover_layout()
            if asset.status != "ready":
                return False
            if asset.source_file_mtime != video.file_mtime or asset.source_file_size != video.file_size:
                return False
            if asset.relative_path != expected_path:
                raise ValueError("Unexpected hover sprite path")
            metadata = asset.metadata_json
            if not isinstance(metadata, dict):
                raise ValueError("Invalid hover preview metadata")
            if (
                metadata.get("sheets") != [expected_path]
                or metadata.get("frame_count") != frame_count
                or metadata.get("duration_seconds") != duration
                or metadata.get("columns") != columns
                or metadata.get("rows") != math.ceil(frame_count / columns)
                or metadata.get("tile_width") != get_settings().hover_preview_tile_width
                or metadata.get("tile_height") != get_settings().hover_preview_tile_height
            ):
                raise ValueError("Incomplete hover preview metadata")
            return AssetService.resolve_relative_path(expected_path).is_file()
        except (OSError, TypeError, ValueError) as exc:
            logger.warning("Hover preview metadata is stale for video %s: %s", video.id, exc)
            return False

    @staticmethod
    async def _assert_source_unchanged(
        video_id: UUID,
        source_path: Path,
        source_size: int,
        source_mtime: datetime,
    ) -> None:
        if not source_path.is_file():
            raise FileNotFoundError("Video source became unavailable during asset generation")
        stat = source_path.stat()
        current_mtime = datetime.fromtimestamp(stat.st_mtime, timezone.utc)
        if stat.st_size != source_size or current_mtime != source_mtime:
            raise RuntimeError("Video source changed during asset generation")
        async with async_session() as session:
            video = await session.get(Video, video_id)
            if (
                video is None
                or video.status != "ready"
                or video.file_size != source_size
                or video.file_mtime != source_mtime
            ):
                raise RuntimeError("Video database source metadata changed during asset generation")

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
    async def mark_stale_previews_pending() -> list[UUID]:
        async with async_session() as session:
            videos = (await session.execute(select(Video).where(Video.status == "ready"))).scalars().all()
            assets = (await session.execute(select(VideoAsset).where(VideoAsset.asset_type == SEEKBAR_PREVIEW))).scalars().all()
            by_video = {asset.video_id: asset for asset in assets}
            queued: list[UUID] = []
            for video in videos:
                asset = by_video.get(video.id)
                stale = asset is None or not AssetService._preview_files_complete(asset, video)
                if not stale:
                    continue
                if asset is None:
                    asset = VideoAsset(video_id=video.id, asset_type=SEEKBAR_PREVIEW, relative_path=AssetService.seekbar_vtt_path(video.id))
                    session.add(asset)
                else:
                    asset.status = "pending"
                    asset.error_message = None
                queued.append(video.id)
            await session.commit()
            return queued

    @staticmethod
    async def request_seekbar_preview(video_id: UUID) -> bool:
        async with async_session() as session:
            video = await session.get(Video, video_id)
            if video is None or video.status != "ready":
                return False
            asset = (await session.execute(select(VideoAsset).where(VideoAsset.video_id == video_id, VideoAsset.asset_type == SEEKBAR_PREVIEW))).scalar_one_or_none()
            if asset is None:
                asset = VideoAsset(video_id=video_id, asset_type=SEEKBAR_PREVIEW, relative_path=AssetService.seekbar_vtt_path(video_id))
                session.add(asset)
            elif asset.status in {"pending", "generating"}:
                return False
            elif AssetService._preview_files_complete(asset, video):
                return False
            asset.status = "pending"
            asset.error_message = None
            await session.commit()
            return True

    @staticmethod
    async def mark_stale_hover_previews_pending() -> list[UUID]:
        async with async_session() as session:
            videos = (await session.execute(select(Video).where(Video.status == "ready"))).scalars().all()
            assets = (await session.execute(select(VideoAsset).where(VideoAsset.asset_type == HOVER_PREVIEW))).scalars().all()
            by_video = {asset.video_id: asset for asset in assets}
            queued: list[UUID] = []
            for video in videos:
                asset = by_video.get(video.id)
                stale = asset is None or not AssetService._hover_preview_file_complete(asset, video)
                if not stale:
                    continue
                if asset is None:
                    session.add(VideoAsset(
                        video_id=video.id,
                        asset_type=HOVER_PREVIEW,
                        relative_path=AssetService.hover_preview_sprite_path(video.id),
                        status="pending",
                    ))
                else:
                    asset.status = "pending"
                    asset.error_message = None
                queued.append(video.id)
            await session.commit()
            return queued

    @staticmethod
    async def request_hover_preview(video_id: UUID) -> bool:
        async with async_session() as session:
            video = await session.get(Video, video_id)
            if video is None or video.status != "ready":
                return False
            asset = (await session.execute(select(VideoAsset).where(
                VideoAsset.video_id == video_id,
                VideoAsset.asset_type == HOVER_PREVIEW,
            ))).scalar_one_or_none()
            if asset is None:
                asset = VideoAsset(
                    video_id=video_id,
                    asset_type=HOVER_PREVIEW,
                    relative_path=AssetService.hover_preview_sprite_path(video_id),
                )
                session.add(asset)
            elif asset.status in {"pending", "generating"}:
                return False
            elif AssetService._hover_preview_file_complete(asset, video):
                return False
            asset.status = "pending"
            asset.error_message = None
            await session.commit()
            return True

    @staticmethod
    async def generate_hover_preview(video_id: UUID) -> None:
        frame_count, clip_duration, columns = AssetService.hover_layout()
        async with async_session() as session:
            video = await session.get(Video, video_id)
            asset = (await session.execute(select(VideoAsset).where(
                VideoAsset.video_id == video_id,
                VideoAsset.asset_type == HOVER_PREVIEW,
            ))).scalar_one_or_none()
            probe = await session.get(VideoProbe, video_id)
            if video is None or asset is None or video.status != "ready":
                return
            if probe is not None and probe.duration_seconds is not None and (
                not math.isfinite(probe.duration_seconds) or probe.duration_seconds <= 0
            ):
                await AssetService._record_hover_failure(video_id, "Video duration is invalid")
                return
            if probe is not None and not probe.video_codec:
                await AssetService._record_hover_failure(video_id, "Video has no video stream")
                return
            source_duration = float(probe.duration_seconds) if probe and probe.duration_seconds else None
            preview_start = min(source_duration * 0.1, max(0.0, source_duration - clip_duration)) if source_duration else 0.0
            width = max(1, get_settings().hover_preview_tile_width)
            height = max(1, get_settings().hover_preview_tile_height)
            asset.status = "generating"
            asset.relative_path = AssetService.hover_preview_sprite_path(video_id)
            await session.commit()
            source_path = Path(video.file_path)
            source_size, source_mtime = video.file_size, video.file_mtime

        asset_root = Path(get_settings().assets_path).resolve()
        temp_root: Path | None = None
        process: asyncio.subprocess.Process | None = None
        promoted_path: Path | None = None
        try:
            asset_root.mkdir(parents=True, exist_ok=True)
            temp_root = Path(tempfile.mkdtemp(prefix=f".fovea-hover-{video_id}-", dir=asset_root))
            await AssetService._assert_source_unchanged(video_id, source_path, source_size, source_mtime)
            sprite_temp = temp_root / "hover.jpg"
            frame_rate = frame_count / clip_duration
            rows = math.ceil(frame_count / columns)
            filters = (
                f"fps={frame_rate:.6f},trim=duration={clip_duration:.3f},"
                f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
                f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,"
                f"tpad=stop_mode=clone:stop_duration={clip_duration:.3f},"
                f"tile={columns}x{rows}:nb_frames={frame_count}"
            )
            command = [
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-ss", f"{preview_start:.3f}",
                "-i", str(source_path), "-map", "0:v:0", "-an", "-vf", filters,
                "-frames:v", "1", "-q:v", "3", "-y", str(sprite_temp),
            ]
            process = await asyncio.create_subprocess_exec(
                *command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            _, stderr = await asyncio.wait_for(process.communicate(), timeout=120)
            if process.returncode != 0 or not sprite_temp.is_file():
                raise RuntimeError(stderr.decode("utf-8", errors="replace").strip() or "FFmpeg hover sprite generation failed")

            await AssetService._assert_source_unchanged(video_id, source_path, source_size, source_mtime)
            relative_path = AssetService.hover_preview_sprite_path(video_id)
            final_path = AssetService.resolve_relative_path(relative_path)
            final_path.parent.mkdir(parents=True, exist_ok=True)
            sprite_temp.replace(final_path)
            promoted_path = final_path
            await AssetService._assert_source_unchanged(video_id, source_path, source_size, source_mtime)

            async with async_session() as session:
                current = await session.get(Video, video_id)
                asset = (await session.execute(select(VideoAsset).where(
                    VideoAsset.video_id == video_id,
                    VideoAsset.asset_type == HOVER_PREVIEW,
                ))).scalar_one_or_none()
                if (
                    current is None
                    or current.status != "ready"
                    or current.file_size != source_size
                    or current.file_mtime != source_mtime
                    or asset is None
                ):
                    raise RuntimeError("Video database source metadata changed during hover preview generation")
                asset.status = "ready"
                asset.relative_path = relative_path
                asset.generated_at = datetime.now(timezone.utc)
                asset.source_file_size = source_size
                asset.source_file_mtime = source_mtime
                asset.metadata_json = {
                    "sheets": [relative_path],
                    "frame_count": frame_count,
                    "duration_seconds": clip_duration,
                    "columns": columns,
                    "rows": rows,
                    "sample_rate_fps": frame_rate,
                    "start_seconds": preview_start,
                    "tile_width": width,
                    "tile_height": height,
                }
                asset.error_message = None
                await session.commit()
        except asyncio.CancelledError:
            if process is not None:
                await AssetService._cleanup_ffmpeg_process(process)
            if promoted_path is not None:
                promoted_path.unlink(missing_ok=True)
            raise
        except Exception as exc:
            if process is not None:
                await AssetService._cleanup_ffmpeg_process(process)
            if promoted_path is not None:
                promoted_path.unlink(missing_ok=True)
            logger.exception("Hover preview generation failed for video %s", video_id)
            await AssetService._record_hover_failure(video_id, str(exc))
        finally:
            if process is not None:
                await AssetService._cleanup_ffmpeg_process(process)
            if temp_root is not None:
                shutil.rmtree(temp_root, ignore_errors=True)

    @staticmethod
    async def _record_hover_failure(video_id: UUID, message: str) -> None:
        async with async_session() as session:
            asset = (await session.execute(select(VideoAsset).where(
                VideoAsset.video_id == video_id,
                VideoAsset.asset_type == HOVER_PREVIEW,
            ))).scalar_one_or_none()
            if asset is not None:
                asset.status = "failed"
                asset.error_message = message[:1000]
                await session.commit()

    @staticmethod
    async def generate_seekbar_preview(video_id: UUID) -> None:
        async with async_session() as session:
            video = await session.get(Video, video_id)
            asset = (await session.execute(select(VideoAsset).where(VideoAsset.video_id == video_id, VideoAsset.asset_type == SEEKBAR_PREVIEW))).scalar_one_or_none()
            probe = await session.get(VideoProbe, video_id)
            if video is None or asset is None or video.status != "ready":
                return
            if probe is None or probe.duration_seconds is None or not math.isfinite(probe.duration_seconds) or probe.duration_seconds <= 0:
                await AssetService._record_preview_failure(video_id, "Video duration is missing or invalid")
                return
            if not probe.video_codec:
                await AssetService._record_preview_failure(video_id, "Video has no video stream")
                return
            duration = float(probe.duration_seconds)
            width = max(1, get_settings().preview_tile_width)
            height = max(1, get_settings().preview_tile_height)
            columns, max_frames = AssetService.preview_layout(
                get_settings().preview_sprite_columns,
                get_settings().preview_sprite_max_frames,
            )
            asset.status = "generating"
            asset.relative_path = AssetService.seekbar_vtt_path(video_id)
            await session.commit()
            source_path = Path(video.file_path)
            source_size, source_mtime = video.file_size, video.file_mtime

        asset_root = Path(get_settings().assets_path).resolve()
        temp_root: Path | None = None
        process: asyncio.subprocess.Process | None = None
        final_paths: list[Path] = []
        promoted_vtt: Path | None = None
        try:
            asset_root.mkdir(parents=True, exist_ok=True)
            temp_root = Path(tempfile.mkdtemp(prefix=f".fovea-preview-{video_id}-", dir=asset_root))
            if not source_path.is_file():
                raise FileNotFoundError("Video source is unavailable")
            stat = source_path.stat()
            if stat.st_size != source_size or datetime.fromtimestamp(stat.st_mtime, timezone.utc) != source_mtime:
                raise RuntimeError("Video source changed before preview generation")
            frames_dir = temp_root / "frames"
            frames_dir.mkdir()
            frame_pattern = frames_dir / "frame-%08d.jpg"
            command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(source_path), "-map", "0:v:0", "-vf", f"fps=1/10:round=up,scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2", "-q:v", "4", "-y", str(frame_pattern)]
            process = await asyncio.create_subprocess_exec(*command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            _, stderr = await asyncio.wait_for(process.communicate(), timeout=max(120, duration * 2))
            if process.returncode != 0:
                raise RuntimeError(stderr.decode("utf-8", errors="replace").strip() or "FFmpeg preview extraction failed")
            frames = sorted(frames_dir.glob("frame-*.jpg"))
            if not frames:
                raise RuntimeError("FFmpeg produced no preview frames")
            frames = [frame for frame in frames if (int(frame.stem.split("-")[-1]) - 1) * 10 < duration]
            sheets_dir = temp_root / "sheets"
            sheets_dir.mkdir()
            for sheet_index, offset in enumerate(range(0, len(frames), max_frames)):
                batch_count = min(max_frames, len(frames) - offset)
                first_number = int(frames[offset].stem.split("-")[-1])
                rows = math.ceil(batch_count / columns)
                sheet_path = sheets_dir / f"{sheet_index:04d}.jpg"
                # The tile filter emits one completed sprite frame, regardless of
                # how many source frames it consumed. Limit the image2 muxer to
                # that single output so it does not require a filename pattern.
                command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-start_number", str(first_number), "-i", str(frame_pattern), "-vf", f"tile={columns}x{rows}:nb_frames={batch_count}", "-frames:v", "1", "-q:v", "3", "-y", str(sheet_path)]
                process = await asyncio.create_subprocess_exec(*command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
                _, stderr = await asyncio.wait_for(process.communicate(), timeout=60)
                if process.returncode != 0 or not sheet_path.is_file():
                    raise RuntimeError(stderr.decode("utf-8", errors="replace").strip() or "FFmpeg sprite assembly failed")
            vtt_temp = temp_root / "preview.vtt"
            vtt_temp.write_text(AssetService.build_preview_cues(video_id, duration, len(frames), columns, max_frames, width, height), encoding="utf-8")
            if not source_path.is_file():
                raise FileNotFoundError("Video source became unavailable during preview generation")
            final_stat = source_path.stat()
            if final_stat.st_size != source_size or datetime.fromtimestamp(final_stat.st_mtime, timezone.utc) != source_mtime:
                raise RuntimeError("Video source changed during preview generation")
            async with async_session() as session:
                current = await session.get(Video, video_id)
                if current is None or current.status != "ready" or current.file_size != source_size or current.file_mtime != source_mtime:
                    raise RuntimeError("Video database source metadata changed during preview generation")
            for index, staged in enumerate(sorted(sheets_dir.glob("*.jpg"))):
                final = AssetService.resolve_relative_path(AssetService.seekbar_sprite_path(video_id, index))
                final.parent.mkdir(parents=True, exist_ok=True)
                staged.replace(final)
                final_paths.append(final)
            vtt_final = AssetService.resolve_relative_path(AssetService.seekbar_vtt_path(video_id))
            vtt_final.parent.mkdir(parents=True, exist_ok=True)
            vtt_temp.replace(vtt_final)
            promoted_vtt = vtt_final
            final_stat = source_path.stat()
            if final_stat.st_size != source_size or datetime.fromtimestamp(final_stat.st_mtime, timezone.utc) != source_mtime:
                raise RuntimeError("Video source changed while promoting preview assets")
            async with async_session() as session:
                current = await session.get(Video, video_id)
                asset = (await session.execute(select(VideoAsset).where(VideoAsset.video_id == video_id, VideoAsset.asset_type == SEEKBAR_PREVIEW))).scalar_one_or_none()
                if current is None or current.status != "ready" or current.file_size != source_size or current.file_mtime != source_mtime:
                    raise RuntimeError("Video database source metadata changed during preview generation")
                asset.status = "ready"
                asset.generated_at = datetime.now(timezone.utc)
                asset.source_file_size = source_size
                asset.source_file_mtime = source_mtime
                asset.metadata_json = {"sheets": [AssetService.seekbar_sprite_path(video_id, i) for i in range(len(final_paths))], "frame_count": len(frames), "interval_seconds": 10, "columns": columns, "tile_width": width, "tile_height": height, "max_frames_per_sheet": max_frames}
                asset.error_message = None
                await session.commit()
        except asyncio.CancelledError:
            if process is not None:
                await AssetService._cleanup_ffmpeg_process(process)
            raise
        except Exception as exc:
            if process is not None:
                await AssetService._cleanup_ffmpeg_process(process)
            logger.exception("Seekbar preview generation failed for video %s", video_id)
            for path in final_paths:
                path.unlink(missing_ok=True)
            if promoted_vtt is not None:
                promoted_vtt.unlink(missing_ok=True)
            await AssetService._record_preview_failure(video_id, str(exc))
        finally:
            if process is not None:
                await AssetService._cleanup_ffmpeg_process(process)
            if temp_root is not None:
                shutil.rmtree(temp_root, ignore_errors=True)

    @staticmethod
    async def _record_preview_failure(video_id: UUID, message: str) -> None:
        async with async_session() as session:
            asset = (await session.execute(select(VideoAsset).where(VideoAsset.video_id == video_id, VideoAsset.asset_type == SEEKBAR_PREVIEW))).scalar_one_or_none()
            if asset is not None:
                asset.status = "failed"
                asset.error_message = message[:1000]
                await session.commit()

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
            source_size, source_mtime = video.file_size, video.file_mtime
            output_path = AssetService.resolve_relative_path(asset.relative_path)

        temporary_path: Path | None = None
        process: asyncio.subprocess.Process | None = None
        try:
            await AssetService._assert_source_unchanged(video_id, source_path, source_size, source_mtime)
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
            await AssetService._assert_source_unchanged(video_id, source_path, source_size, source_mtime)
            temporary_path.replace(output_path)
            await AssetService._record_thumbnail_success(video_id, timestamp, source_size, source_mtime)
        except asyncio.CancelledError:
            if process is not None:
                await AssetService._cleanup_ffmpeg_process(process)
            raise
        except TimeoutError as exc:
            if process is not None:
                await AssetService._cleanup_ffmpeg_process(process)
            message = f"FFmpeg timed out after 90 seconds: {exc}"
            logger.error("Thumbnail generation failed for video %s: %s", video_id, message)
            await AssetService._record_thumbnail_failure(video_id, message)
        except Exception as exc:
            if process is not None:
                await AssetService._cleanup_ffmpeg_process(process)
            logger.exception("Thumbnail generation failed for video %s", video_id)
            await AssetService._record_thumbnail_failure(video_id, str(exc))
        finally:
            if process is not None:
                await AssetService._cleanup_ffmpeg_process(process)
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)

    @staticmethod
    async def _record_thumbnail_success(
        video_id: UUID,
        timestamp: float,
        source_size: int,
        source_mtime: datetime,
    ) -> None:
        async with async_session() as session:
            video = await session.get(Video, video_id)
            if (
                video is None
                or video.status != "ready"
                or video.file_size != source_size
                or video.file_mtime != source_mtime
            ):
                raise RuntimeError("Video database source metadata changed during thumbnail generation")
            asset = (
                await session.execute(select(VideoAsset).where(VideoAsset.video_id == video_id, VideoAsset.asset_type == THUMBNAIL))
            ).scalar_one()
            asset.status = "ready"
            asset.generated_at = datetime.now(timezone.utc)
            asset.source_file_mtime = source_mtime
            asset.source_file_size = source_size
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
        if asset_type == HOVER_PREVIEW:
            await AssetService.generate_hover_preview(video_id)
            return
        if asset_type == SEEKBAR_PREVIEW:
            await AssetService.generate_seekbar_preview(video_id)
            return
        if asset_type != THUMBNAIL:
            raise ValueError(f"Unsupported asset type: {asset_type}")
        await AssetService.generate_thumbnail(video_id)
