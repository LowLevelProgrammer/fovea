"""In-process worker that consumes probe jobs from PostgreSQL."""

import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from app.db.session import async_session
from app.models.job import Job
from app.models.video import Video
from app.models.video_probe import VideoProbe
from app.services.job_service import JobService
from app.services.probe_service import ProbeError, ProbeResult, ProbeService

logger = logging.getLogger(__name__)


class ProbeWorker:
    """Polls for probe jobs and persists FFprobe results."""

    POLL_INTERVAL_SECONDS = 2.0

    async def run(self) -> None:
        """Run the worker loop until cancelled."""
        while True:
            try:
                job = await JobService.claim_next_probe_job()
                if job is None:
                    await asyncio.sleep(self.POLL_INTERVAL_SECONDS)
                    continue

                await self._process_job(job)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("ProbeWorker loop error")
                await asyncio.sleep(self.POLL_INTERVAL_SECONDS)

    async def _process_job(self, job: Job) -> None:
        try:
            file_path = await self._prepare_video(job.id, job.video_id)
            if file_path is None:
                return

            probe_result = await ProbeService.probe(file_path)
            await self._persist_probe_success(job.id, job.video_id, probe_result)
        except ProbeError as exc:
            logger.warning(
                "Probe failed for job %s video %s: %s",
                job.id,
                job.video_id,
                exc,
            )
            await self._handle_failure(job.id, job.video_id, str(exc))
        except Exception as exc:
            logger.exception(
                "Unexpected error processing job %s video %s",
                job.id,
                job.video_id,
            )
            await self._handle_failure(job.id, job.video_id, str(exc))

    async def _prepare_video(self, job_id: UUID, video_id: UUID) -> str | None:
        async with async_session() as session:
            video = await session.get(Video, video_id)
            if video is None:
                await JobService.fail_job(job_id, f"Video not found: {video_id}")
                return None

            path = Path(video.file_path)
            if not path.exists() or not path.is_file():
                video.status = "error"
                await session.commit()
                await JobService.fail_job(job_id, f"Video file not found: {video.file_path}")
                return None

            video.status = "probing"
            await session.commit()
            return video.file_path

    async def _persist_probe_success(
        self,
        job_id: UUID,
        video_id: UUID,
        probe_result: ProbeResult,
    ) -> None:
        async with async_session() as session:
            video = await session.get(Video, video_id)
            if video is None:
                await JobService.fail_job(job_id, f"Video not found: {video_id}")
                return

            probe_row = await session.get(VideoProbe, video_id)
            if probe_row is None:
                probe_row = VideoProbe(video_id=video_id)
                session.add(probe_row)

            now = datetime.now(timezone.utc)
            probe_row.duration_seconds = probe_result.duration_seconds
            probe_row.container_format = probe_result.container_format
            probe_row.video_codec = probe_result.video_codec
            probe_row.audio_codec = probe_result.audio_codec
            probe_row.width = probe_result.width
            probe_row.height = probe_result.height
            probe_row.frame_rate = probe_result.frame_rate
            probe_row.bitrate = probe_result.bitrate
            probe_row.raw_ffprobe = probe_result.raw_ffprobe
            probe_row.probed_at = now

            video.status = "ready"
            await session.commit()

        await JobService.complete_job_with_retry(
            job_id,
            {
                "duration_seconds": probe_result.duration_seconds,
                "container_format": probe_result.container_format,
                "video_codec": probe_result.video_codec,
                "audio_codec": probe_result.audio_codec,
                "width": probe_result.width,
                "height": probe_result.height,
            },
        )

    async def _handle_failure(self, job_id: UUID, video_id: UUID, error_message: str) -> None:
        async with async_session() as session:
            video = await session.get(Video, video_id)
            if video is not None and video.status == "probing":
                video.status = "error"
                await session.commit()

        await JobService.fail_job(job_id, error_message)
