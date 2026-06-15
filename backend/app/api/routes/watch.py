from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api.schemas.watch_session import WatchSessionUpdate, WatchSessionRead
from app.db.session import async_session
from app.models.video import Video
from app.models.watch_session import WatchSession

router = APIRouter(tags=["watch"])


@router.put("/sessions/{video_id}", response_model=WatchSessionRead)
async def update_watch_session(
    video_id: UUID,
    payload: WatchSessionUpdate,
) -> WatchSessionRead:
    """
    Create or update the watch progress session for a video.

    Path params:
    - video_id (UUID): ID of the video

    Request:
    - position_seconds (float): Playback position in seconds
    - duration_seconds (float, optional): Duration of the video in seconds
    """
    async with async_session() as session:
        # 1. Verify video exists
        video_result = await session.execute(select(Video).where(Video.id == video_id))
        video = video_result.scalar_one_or_none()
        if not video:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Video not found.",
            )

        # Helper to check completion based on duration
        def _check_completed(position: float, duration: float | None) -> bool:
            if duration is not None and duration > 0:
                return position >= 0.95 * duration
            return False

        # 2. Check if a session already exists for this video_id and user_id = NULL
        query = select(WatchSession).where(
            WatchSession.video_id == video_id, WatchSession.user_id.is_(None)
        )
        result = await session.execute(query)
        watch_session = result.scalar_one_or_none()

        duration = payload.duration_seconds
        if duration is None and watch_session is not None:
            duration = watch_session.duration_seconds

        completed = _check_completed(payload.position_seconds, duration)

        if watch_session is None:
            # Create a new session
            watch_session = WatchSession(
                video_id=video_id,
                user_id=None,
                position_seconds=payload.position_seconds,
                duration_seconds=payload.duration_seconds,
                completed=completed,
            )
            session.add(watch_session)
        else:
            # Update existing session
            watch_session.position_seconds = payload.position_seconds
            if payload.duration_seconds is not None:
                watch_session.duration_seconds = payload.duration_seconds
            watch_session.completed = completed
            session.add(watch_session)

        # 3. Commit with IntegrityError handling for race conditions
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            # If a concurrent request created it first, fetch and update it
            result = await session.execute(query)
            watch_session = result.scalar_one_or_none()
            if watch_session:
                watch_session.position_seconds = payload.position_seconds
                if payload.duration_seconds is not None:
                    watch_session.duration_seconds = payload.duration_seconds
                watch_session.completed = _check_completed(
                    payload.position_seconds,
                    payload.duration_seconds
                    if payload.duration_seconds is not None
                    else watch_session.duration_seconds,
                )
                session.add(watch_session)
                await session.commit()
            else:
                raise

        await session.refresh(watch_session)

    return WatchSessionRead.model_validate(watch_session)
