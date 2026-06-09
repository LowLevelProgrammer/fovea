from dataclasses import dataclass
from datetime import datetime
from pathlib import PurePosixPath
from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.db.session import async_session
from app.models.watch_path import WatchPath
from app.models.video import Video
from app.services.job_service import JobService
from app.services.video_scanner import VideoScanner


def _is_under_watch_path(file_path: str, watch_path: str) -> bool:
    file_path_obj = PurePosixPath(file_path)
    watch_path_obj = PurePosixPath(watch_path)

    return (
        file_path_obj == watch_path_obj
        or watch_path_obj in file_path_obj.parents
    )


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

    @staticmethod
    async def scan(watch_path_id: Optional[UUID] = None) -> ScanResult:
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
        start_time = datetime.now(tz=datetime.now().astimezone().tzinfo)
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
                    raise ValueError(f"Watch path not found: {watch_path_id}")
            else:
                result = await session.execute(select(WatchPath).where(WatchPath.enabled == True))
                paths_to_scan = result.scalars().all()

            # 2. Discover files from each watch path
            for wp in paths_to_scan:
                if not wp.enabled:
                    continue

                try:
                    scanner = VideoScanner()
                    discovered = await scanner.scan_path(wp.path)
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
                                added_at=datetime.now(tz=datetime.now().astimezone().tzinfo),
                                last_seen_at=datetime.now(tz=datetime.now().astimezone().tzinfo),
                            )
                            session.add(video)
                            videos_to_probe.append(video)  # Track ORM object for probe enqueueing
                        elif existing_video.status == "unavailable":
                            # Scenario 2b: Reappearing file
                            existing_video.status = "discovered"
                            existing_video.last_seen_at = datetime.now(tz=datetime.now().astimezone().tzinfo)
                            existing_video.unavailable_since = None
                            existing_video.file_size = df.file_size
                            existing_video.file_mtime = df.file_mtime
                            existing_video.fingerprint = df.fingerprint
                            session.add(existing_video)
                            videos_to_probe.append(existing_video)  # Track ORM object for probe enqueueing
                        else:
                            # Scenario 2a: Seen again (available)
                            # Do NOT enqueue a new probe job
                            existing_video.last_seen_at = datetime.now(tz=datetime.now().astimezone().tzinfo)
                            existing_video.file_size = df.file_size
                            existing_video.file_mtime = df.file_mtime
                            existing_video.fingerprint = df.fingerprint
                            session.add(existing_video)

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
            now = datetime.now(tz=datetime.now().astimezone().tzinfo)

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

        elapsed = (datetime.now(tz=datetime.now().astimezone().tzinfo) - start_time).total_seconds()

        return ScanResult(
            watch_paths_scanned=watch_paths_scanned,
            videos_discovered=len(discovered_paths),
            videos_unavailable=videos_unavailable,
            duration_seconds=elapsed,
            started_at=start_time,
        )
