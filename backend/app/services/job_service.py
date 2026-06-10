"""Job service for managing probe job lifecycle in PostgreSQL."""

import asyncio
import logging
from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import async_session
from app.models.job import Job

logger = logging.getLogger(__name__)


class JobService:
    """Service for managing jobs stored in PostgreSQL."""

    COMPLETE_JOB_MAX_ATTEMPTS = 3
    COMPLETE_JOB_RETRY_DELAY_SECONDS = 0.5

    @staticmethod
    async def has_active_probe_job(video_id: UUID) -> bool:
        """
        Check if an active probe job already exists for a video.

        A job is considered active if its status is 'pending' or 'in_progress'.

        Args:
            video_id: UUID of the video to check

        Returns:
            True if an active probe job exists, False otherwise
        """
        async with async_session() as session:
            result = await session.execute(
                select(Job).where(
                    (Job.video_id == video_id)
                    & (Job.job_type == "probe")
                    & (Job.status.in_(["pending", "in_progress"]))
                )
            )
            return result.scalar_one_or_none() is not None

    @staticmethod
    async def create_probe_job(video_id: UUID) -> UUID:
        """
        Create a new pending probe job for a video.

        Caller is responsible for checking duplicates via has_active_probe_job().

        Args:
            video_id: UUID of the video to probe

        Returns:
            UUID of the created job
        """
        async with async_session() as session:
            job = Job(
                video_id=video_id,
                job_type="probe",
                status="pending",
                attempt_count=0,
                max_attempts=3,
            )
            session.add(job)
            await session.commit()
            await session.refresh(job)
            return job.id

    @staticmethod
    async def claim_next_probe_job() -> Optional[Job]:
        """
        Claim the oldest pending probe job atomically.

        Race-condition handling:
        - Uses database-level row locking (SELECT ... FOR UPDATE)
        - Wrapped in explicit transaction to ensure atomicity
        - Only one concurrent worker can claim a specific job
        - Status updated and attempt_count incremented before release

        Returns:
            Claimed Job instance, or None if no pending job
        """
        async with async_session() as session:
            async with session.begin():
                # SELECT ... FOR UPDATE locks the row until transaction commits
                result = await session.execute(
                    select(Job)
                    .where(
                        Job.status == "pending",
                        Job.job_type == "probe",
                    )
                    .order_by(Job.created_at)
                    .limit(1)
                    .with_for_update(skip_locked=True)
                )
                job = result.scalar_one_or_none()

                if job is None:
                    return None

                # Update job state within the locked transaction
                job.status = "in_progress"
                job.attempt_count += 1
                await session.flush()

            # Transaction commits here, releasing the lock
            # Refresh to get updated timestamps
            await session.refresh(job)

            return job

    @staticmethod
    async def _apply_job_completion(
        session: AsyncSession, job_id: UUID, result: Optional[dict]
    ) -> None:
        job = await session.get(Job, job_id)
        if job is None:
            raise ValueError(f"Job not found: {job_id}")

        job.status = "completed"
        job.result = result

    @staticmethod
    async def complete_job(job_id: UUID, result: Optional[dict] = None) -> None:
        """
        Mark a job as completed with optional result data.

        Args:
            job_id: UUID of the job to complete
            result: Optional dictionary of result data to store
        """
        async with async_session() as session:
            await JobService._apply_job_completion(session, job_id, result)
            await session.commit()

    @staticmethod
    async def complete_job_with_retry(job_id: UUID, result: Optional[dict] = None) -> None:
        """
        Mark a job completed, retrying transient failures.

        After probe data is persisted, callers use this so a job cannot remain
        in_progress due to a one-off DB error during completion.
        """
        last_error: Exception | None = None
        for attempt in range(JobService.COMPLETE_JOB_MAX_ATTEMPTS):
            try:
                await JobService.complete_job(job_id, result)
                return
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "complete_job attempt %d/%d failed for job %s: %s",
                    attempt + 1,
                    JobService.COMPLETE_JOB_MAX_ATTEMPTS,
                    job_id,
                    exc,
                )
                if attempt < JobService.COMPLETE_JOB_MAX_ATTEMPTS - 1:
                    await asyncio.sleep(JobService.COMPLETE_JOB_RETRY_DELAY_SECONDS)

        logger.error(
            "complete_job retries exhausted for job %s; using fallback completion",
            job_id,
        )
        try:
            async with async_session() as session:
                await JobService._apply_job_completion(session, job_id, result)
                await session.commit()
        except Exception as exc:
            if last_error is not None:
                raise last_error from exc
            raise

        logger.warning("complete_job fallback succeeded for job %s", job_id)

    @staticmethod
    async def fail_job(job_id: UUID, error_message: str) -> None:
        """
        Mark a job as failed with an error message.

        Does not increment attempt_count; that happens in claim_next_probe_job().
        If attempt_count is still below max_attempts, status is reset to "pending"
        for retry. Otherwise, status is set to "failed".

        Args:
            job_id: UUID of the job to fail
            error_message: Error message describing the failure
        """
        async with async_session() as session:
            job_result = await session.execute(select(Job).where(Job.id == job_id))
            job = job_result.scalar_one_or_none()

            if job is None:
                raise ValueError(f"Job not found: {job_id}")

            job.error_message = error_message

            # Check if we can retry
            if job.attempt_count < job.max_attempts:
                job.status = "pending"
            else:
                job.status = "failed"

            session.add(job)
            await session.commit()
