import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import PurePosixPath
from typing import Optional
from uuid import UUID

from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError

from app.db.session import async_session
from app.models.watch_path import WatchPath
from app.models.video import Video
from app.models.tag import Tag, VideoTag
from app.services.job_service import JobService
from app.services.video_scanner import VideoScanner


class WatchPathNotFoundError(ValueError):
    """Requested watch path does not exist."""

    pass


def _is_under_watch_path(file_path: str, watch_path: str) -> bool:
    file_path_obj = PurePosixPath(file_path)
    watch_path_obj = PurePosixPath(watch_path)

    return (
        file_path_obj == watch_path_obj
        or watch_path_obj in file_path_obj.parents
    )


async def _apply_auto_tags(session, video: Video, file_path: str, watch_root: str) -> None:
    # TODO: Scan-performance optimization
    # This method is currently called sequentially for every video during a scan, causing a severe 
    # N+1 query problem (executing at least 2 database queries per file).
    # After discovery features are functional, this should be refactored to bulk-process tags
    # outside of the file-by-file ingestion loop.
    try:
        rel_path = PurePosixPath(file_path).relative_to(PurePosixPath(watch_root))
        folders = [part for part in rel_path.parent.parts if part and part != "."]
    except ValueError:
        folders = []

    desired_folders = {f.strip() for f in folders if f.strip()}

    stmt = select(VideoTag).where(VideoTag.video_id == video.id)
    result = await session.execute(stmt)
    existing_associations = result.scalars().all()

    assoc_by_tag_id = {assoc.tag_id: assoc for assoc in existing_associations}

    if assoc_by_tag_id:
        tag_stmt = select(Tag).where(Tag.id.in_(assoc_by_tag_id.keys()))
        tag_result = await session.execute(tag_stmt)
        tags_by_id = {tag.id: tag for tag in tag_result.scalars().all()}
    else:
        tags_by_id = {}

    auto_assocs_to_remove = []
    associated_folder_names_lower = set()

    for tag_id, assoc in assoc_by_tag_id.items():
        tag = tags_by_id.get(tag_id)
        if not tag:
            continue
        tag_name_lower = tag.name.lower()
        if assoc.source == "auto":
            if tag_name_lower not in {f.lower() for f in desired_folders}:
                auto_assocs_to_remove.append(assoc)
            else:
                associated_folder_names_lower.add(tag_name_lower)
        else:
            associated_folder_names_lower.add(tag_name_lower)

    for assoc in auto_assocs_to_remove:
        await session.delete(assoc)

    for folder in desired_folders:
        folder_lower = folder.lower()
        if folder_lower in associated_folder_names_lower:
            continue

        tag_stmt = select(Tag).where(func.lower(Tag.name) == folder_lower)
        tag_result = await session.execute(tag_stmt)
        tag = tag_result.scalar_one_or_none()

        if not tag:
            tag = Tag(name=folder)
            session.add(tag)
            await session.flush()

        new_assoc = VideoTag(video_id=video.id, tag_id=tag.id, source="auto")
        session.add(new_assoc)


@dataclass
class ScanResult:
    """Result of a scan operation."""
    watch_paths_scanned: int
    videos_discovered: int
    videos_unavailable: int
    duration_seconds: float
    started_at: datetime


class ScanService:
    """Orchestrates the scanning and ingestion of videos from watch paths."""

    _scan_lock: Optional[asyncio.Lock] = None

    @classmethod
    def _get_scan_lock(cls) -> asyncio.Lock:
        if cls._scan_lock is None:
            cls._scan_lock = asyncio.Lock()
        return cls._scan_lock

    @classmethod
    async def scan(cls, watch_path_id: Optional[UUID] = None) -> ScanResult:
        """
        Scan enabled watch paths and update the videos table.

        Lifecycle:
        - New files: INSERT with status='discovered', added_at=now()
        - Existing files: UPDATE last_seen_at=now(), file_size/mtime/fingerprint
        - Missing files: UPDATE status='unavailable', unavailable_since=now()
        - Reappearing files: UPDATE status='discovered', unavailable_since=null

        Probe jobs are enqueued for new and reappearing videos (unless duplicate active jobs exist).

        Args:
            watch_path_id: Optional UUID to scan a single watch path; if None, scans all enabled paths

        Returns:
            ScanResult with operation statistics

        Raises:
            FileNotFoundError: If a watch path does not exist
            PermissionError: If a watch path is not readable
        """
        async with cls._get_scan_lock():
            start_time = datetime.now(timezone.utc)
            discovered_paths: set[str] = set()
            watch_paths_scanned = 0
            videos_to_probe: list[Video] = []  # Track ORM objects needing probes

            async with async_session() as session:
                # 1. Fetch watch paths to scan
                if watch_path_id:
                    result = await session.execute(
                        select(WatchPath).where(WatchPath.id == watch_path_id)
                    )
                    paths_to_scan = [result.scalar_one_or_none()]
                    if not paths_to_scan[0]:
                        raise WatchPathNotFoundError(
                            f"Watch path not found: {watch_path_id}"
                        )
                else:
                    result = await session.execute(select(WatchPath).where(WatchPath.enabled.is_(True)))
                    paths_to_scan = result.scalars().all()

                # 2. Discover files from each watch path
                for wp in paths_to_scan:
                    if not wp.enabled:
                        continue

                    try:
                        scanner = VideoScanner()
                        discovered = await scanner.scan_path(wp.path, wp.scan_recursive)
                        discovered_paths.update(df.file_path for df in discovered)

                        # 3. Upsert discovered files
                        for df in discovered:
                            existing = await session.execute(
                                select(Video).where(Video.file_path == df.file_path)
                            )
                            existing_video = existing.scalar_one_or_none()

                            if not existing_video:
                                # Scenario 1: New file
                                video = Video(
                                    file_path=df.file_path,
                                    title=df.title,
                                    file_size=df.file_size,
                                    file_mtime=df.file_mtime,
                                    fingerprint=df.fingerprint,
                                    status="discovered",
                                    added_at=datetime.now(timezone.utc),
                                    last_seen_at=datetime.now(timezone.utc),
                                )
                                session.add(video)
                                await session.flush()
                                await _apply_auto_tags(session, video, df.file_path, wp.path)
                                videos_to_probe.append(video)  # Track ORM object for probe enqueueing
                            elif existing_video.status == "unavailable":
                                # Scenario 2b: Reappearing file
                                existing_video.status = "discovered"
                                existing_video.last_seen_at = datetime.now(timezone.utc)
                                existing_video.unavailable_since = None
                                existing_video.file_size = df.file_size
                                existing_video.file_mtime = df.file_mtime
                                existing_video.fingerprint = df.fingerprint
                                session.add(existing_video)
                                await _apply_auto_tags(session, existing_video, df.file_path, wp.path)
                                videos_to_probe.append(existing_video)  # Track ORM object for probe enqueueing
                            else:
                                # Scenario 2a: Seen again (available)
                                # Do NOT enqueue a new probe job
                                existing_video.last_seen_at = datetime.now(timezone.utc)
                                existing_video.file_size = df.file_size
                                existing_video.file_mtime = df.file_mtime
                                existing_video.fingerprint = df.fingerprint
                                session.add(existing_video)
                                await _apply_auto_tags(session, existing_video, df.file_path, wp.path)


                        watch_paths_scanned += 1

                    except (FileNotFoundError, PermissionError):
                        # Skip inaccessible watch paths but continue scanning others
                        continue

                # 4. Flush to populate UUIDs (server-side defaults), then commit
                await session.flush()  # Populate video.id before commit
                try:
                    await session.commit()
                except IntegrityError:
                    await session.rollback()
                    raise RuntimeError("Failed to upsert videos due to constraint violation")

                # 5. Mark videos not found as unavailable (Scenario 3)
                now = datetime.now(timezone.utc)

                result = await session.execute(
                    select(Video).where(Video.status != "unavailable")
                )
                all_available_videos = result.scalars().all()

                if watch_path_id is None:
                    # Full library scan:
                    # Consider every available video in the database.
                    candidate_videos = all_available_videos

                else:
                    # Targeted scan:
                    # Only consider videos that belong to the scanned watch path.
                    target_watch_path = paths_to_scan[0]
                    watch_root = target_watch_path.path

                    candidate_videos = [
                        video
                        for video in all_available_videos
                        if _is_under_watch_path(video.file_path, watch_root)
                    ]

                videos_unavailable = 0
                for video in candidate_videos:
                    if video.file_path not in discovered_paths:
                        video.status = "unavailable"
                        video.unavailable_since = now
                        session.add(video)
                        videos_unavailable += 1

                # 6. Commit unavailability updates
                try:
                    await session.commit()
                except IntegrityError:
                    await session.rollback()
                    raise RuntimeError("Failed to mark videos as unavailable")

                # 7. Enqueue probe jobs for new/reappearing videos
                # Use tracked ORM objects (UUIDs populated during flush() in step 4)
                # Duplicate-prevention strategy: Best-effort check (not race-free)
                # - has_active_probe_job() queries for pending/in_progress probe jobs
                # - If found, skip creation; otherwise, create new job
                # - Race condition possible: between check and creation, another worker may create job
                # - Acceptable for Phase 1 (single in-process worker); worst case = duplicate pending job
                for video in videos_to_probe:
                    if not await JobService.has_active_probe_job(video.id):
                        await JobService.create_probe_job(video.id)

            elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()

            return ScanResult(
                watch_paths_scanned=watch_paths_scanned,
                videos_discovered=len(discovered_paths),
                videos_unavailable=videos_unavailable,
                duration_seconds=elapsed,
                started_at=start_time,
            )
