"""Job service for managing probe job lifecycle in PostgreSQL."""

from typing import Optional
from uuid import UUID

from sqlalchemy import select

from app.db.session import async_session
from app.models.job import Job


class JobService:
    """Service for managing jobs stored in PostgreSQL."""

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
                    .where(Job.status == "pending")
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
    async def complete_job(job_id: UUID, result: Optional[dict] = None) -> None:
        """
        Mark a job as completed with optional result data.

        Args:
            job_id: UUID of the job to complete
            result: Optional dictionary of result data to store
        """
        async with async_session() as session:
            job_result = await session.execute(select(Job).where(Job.id == job_id))
            job = job_result.scalar_one_or_none()

            if job is None:
                raise ValueError(f"Job not found: {job_id}")

            job.status = "completed"
            job.result = result
            session.add(job)
            await session.commit()

    @staticmethod
    async def fail_job(job_id: UUID, error_message: str) -> None:
        """
        Mark a job as failed with an error message.

        Increments attempt_count. If max_attempts is reached, status remains "failed".
        Otherwise, status is reset to "pending" to allow retry.

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
