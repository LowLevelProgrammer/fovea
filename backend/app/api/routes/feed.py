from fastapi import APIRouter, Query
from sqlalchemy import select

from app.api.schemas.feed import FeedResponse, RankedFeedPage
from app.api.schemas.video import VideoListItem
from app.db.session import async_session
from app.models.watch_session import WatchSession
from app.services.recommendation_service import RecommendationService

router = APIRouter(tags=["feed"])


def _feed_item(video, watch_session: WatchSession | None = None, reason: str | None = None) -> VideoListItem:
    item = VideoListItem.model_validate(video)
    return item.model_copy(
        update={
            "recommendation_reason": reason,
            "duration_seconds": watch_session.duration_seconds if watch_session else None,
            "resume_position_seconds": watch_session.position_seconds if watch_session else None,
            "completed": watch_session.completed if watch_session else None,
        }
    )


@router.get("/home", response_model=FeedResponse)
async def get_homepage_feed(
    offset: int = Query(0, ge=0),
    limit: int = Query(24, ge=1, le=100),
) -> FeedResponse:
    """Return a Continue Watching rail and one paginated ranked discovery feed."""
    async with async_session() as session:
        continue_watching = await RecommendationService.get_continue_watching(session)
        continue_ids = {video.id for video in continue_watching}
        ranked, total = await RecommendationService.get_ranked_feed(
            session, limit=limit, offset=offset, exclude_ids=continue_ids
        )

        item_ids = [video.id for video in continue_watching] + [item.video.id for item in ranked]
        watch_sessions: dict = {}
        if item_ids:
            session_rows = await session.execute(
                select(WatchSession).where(
                    WatchSession.video_id.in_(item_ids), WatchSession.user_id.is_(None)
                )
            )
            watch_sessions = {watch.video_id: watch for watch in session_rows.scalars().all()}

        return FeedResponse(
            continue_watching=[_feed_item(video, watch_sessions.get(video.id)) for video in continue_watching],
            recommendations=RankedFeedPage(
                items=[_feed_item(item.video, watch_sessions.get(item.video.id), item.reason) for item in ranked],
                offset=offset,
                limit=limit,
                total=total,
                has_more=offset + len(ranked) < total,
            ),
        )
