from fastapi import APIRouter
from sqlalchemy import select
from app.api.schemas.feed import FeedResponse, FeedSection
from app.api.schemas.video import VideoListItem
from app.db.session import async_session
from app.models.video import Video
from app.models.watch_session import WatchSession
from app.services.recommendation_service import RecommendationService

router = APIRouter(tags=["feed"])

@router.get("/home", response_model=FeedResponse)
async def get_homepage_feed() -> FeedResponse:
    """
    Retrieve the homepage feed with various sections (e.g. Recently Added, Continue Watching).
    """
    sections = []
    exclude_ids = set()

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
            exclude_ids.update(v.id for v in cw_videos)

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
                    items=[
                        VideoListItem(
                            **VideoListItem.model_validate(v).model_dump(exclude={"recommendation_reason"}),
                            recommendation_reason="Recently added"
                        ) for v in ra_videos
                    ],
                )
            )
            exclude_ids.update(v.id for v in ra_videos)

        # 3. Frequently Watched
        fw_videos_with_reasons = await RecommendationService.get_frequently_watched(session, limit=12, exclude_ids=exclude_ids)
        if fw_videos_with_reasons:
            sections.append(
                FeedSection(
                    id="frequently_watched",
                    title="Frequently Watched",
                    type="frequently_watched",
                    items=[
                        VideoListItem(
                            **VideoListItem.model_validate(v).model_dump(exclude={"recommendation_reason"}),
                            recommendation_reason=r
                        ) for v, r in fw_videos_with_reasons
                    ],
                )
            )
            exclude_ids.update(v.id for v, r in fw_videos_with_reasons)

        # 4. Recommended For You
        rfy_videos_with_reasons = await RecommendationService.get_recommended_for_you(session, limit=12, exclude_ids=exclude_ids)
        if rfy_videos_with_reasons:
            sections.append(
                FeedSection(
                    id="recommended_for_you",
                    title="Recommended For You",
                    type="recommended",
                    items=[
                        VideoListItem(
                            **VideoListItem.model_validate(v).model_dump(exclude={"recommendation_reason"}),
                            recommendation_reason=r
                        ) for v, r in rfy_videos_with_reasons
                    ],
                )
            )
            exclude_ids.update(v.id for v, r in rfy_videos_with_reasons)

        # 5. Random Discovery
        rd_videos_with_reasons = await RecommendationService.get_random_discovery(session, limit=12, exclude_ids=exclude_ids)
        if rd_videos_with_reasons:
            sections.append(
                FeedSection(
                    id="random_discovery",
                    title="Discover Something New",
                    type="random",
                    items=[
                        VideoListItem(
                            **VideoListItem.model_validate(v).model_dump(exclude={"recommendation_reason"}),
                            recommendation_reason=r
                        ) for v, r in rd_videos_with_reasons
                    ],
                )
            )
        # The feed is the only discovery response that knows a card is being
        # shown in a watch context. Attach the existing watch-session data so
        # clients can render progress without issuing one request per card.
        video_ids = [item.id for section in sections for item in section.items]
        if video_ids:
            watch_result = await session.execute(
                select(WatchSession).where(
                    WatchSession.video_id.in_(video_ids),
                    WatchSession.user_id.is_(None),
                )
            )
            sessions_by_video_id = {
                watch_session.video_id: watch_session
                for watch_session in watch_result.scalars().all()
            }
            for section in sections:
                section.items = [
                    item.model_copy(
                        update={
                            "duration_seconds": watch_session.duration_seconds,
                            "resume_position_seconds": watch_session.position_seconds,
                            "completed": watch_session.completed,
                        }
                    )
                    if (watch_session := sessions_by_video_id.get(item.id))
                    else item
                    for item in section.items
                ]

    return FeedResponse(sections=sections)
