from fastapi import APIRouter
from sqlalchemy import select
from app.api.schemas.feed import FeedResponse, FeedSection
from app.api.schemas.video import VideoListItem
from app.db.session import async_session
from app.models.video import Video
from app.models.watch_session import WatchSession

router = APIRouter(tags=["feed"])

@router.get("/home", response_model=FeedResponse)
async def get_homepage_feed() -> FeedResponse:
    """
    Retrieve the homepage feed with various sections (e.g. Recently Added, Continue Watching).
    """
    sections = []

    async with async_session() as session:
        # 1. Continue Watching
        cw_stmt = (
            select(Video)
            .join(WatchSession, WatchSession.video_id == Video.id)
            .where(
                Video.status != "unavailable",
                WatchSession.completed.is_(False),
                WatchSession.position_seconds > 0,
            )
            .order_by(WatchSession.updated_at.desc())
            .limit(12)
        )
        cw_result = await session.execute(cw_stmt)
        cw_videos = cw_result.scalars().all()

        if cw_videos:
            sections.append(
                FeedSection(
                    id="continue_watching",
                    title="Continue Watching",
                    type="continue_watching",
                    items=[VideoListItem.model_validate(v) for v in cw_videos],
                )
            )

        # 2. Recently Added
        ra_stmt = (
            select(Video)
            .where(Video.status != "unavailable")
            .order_by(Video.added_at.desc())
            .limit(24)
        )
        ra_result = await session.execute(ra_stmt)
        ra_videos = ra_result.scalars().all()

        if ra_videos:
            sections.append(
                FeedSection(
                    id="recently_added",
                    title="Recently Added",
                    type="recently_added",
                    items=[VideoListItem.model_validate(v) for v in ra_videos],
                )
            )

    return FeedResponse(sections=sections)
