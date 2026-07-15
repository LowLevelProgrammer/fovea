from typing import Optional
from uuid import UUID
from sqlalchemy import select, func, case, desc
from sqlalchemy.orm import selectinload
from app.models.video import Video
from app.models.tag import Tag, VideoTag
from app.models.watch_session import WatchSession

class RecommendationService:
    @staticmethod
    async def get_frequently_watched(session, limit: int = 12, exclude_ids: Optional[set[UUID]] = None) -> list[tuple[Video, str]]:
        stmt = select(Video).where(Video.status != "unavailable", Video.watch_count > 0)
        if exclude_ids:
            stmt = stmt.where(Video.id.notin_(exclude_ids))
        
        stmt = stmt.order_by(Video.watch_count.desc(), Video.last_watched_at.desc().nulls_last()).limit(limit)
        result = await session.execute(stmt)
        videos = result.scalars().all()
        return [(v, "Popular in your library") for v in videos]

    @staticmethod
    async def get_random_discovery(session, limit: int = 12, exclude_ids: Optional[set[UUID]] = None) -> list[tuple[Video, str]]:
        # Prefer unwatched or low-watch-count videos
        # Random sort using random()
        stmt = select(Video).where(Video.status != "unavailable")
        if exclude_ids:
            stmt = stmt.where(Video.id.notin_(exclude_ids))
            
        # Order by unwatched first, then low watch count, then random
        stmt = stmt.order_by(
            Video.watch_count.asc(),
            func.random()
        ).limit(limit)
        
        result = await session.execute(stmt)
        videos = result.scalars().all()
        return [(v, "Random pick") for v in videos]

    @staticmethod
    async def get_recommended_for_you(session, limit: int = 12, exclude_ids: Optional[set[UUID]] = None) -> list[tuple[Video, str]]:
        import random
        random_limit = max(1, int(limit * 0.2))
        rec_limit = limit - random_limit

        # Get watched videos to exclude them from recommendations
        watched_stmt = select(WatchSession.video_id).distinct()
        watched_result = await session.execute(watched_stmt)
        watched_video_ids = {row[0] for row in watched_result.all()}
        
        # Get tags from videos watched recently or completed
        profile_stmt = (
            select(VideoTag.tag_id, Tag.name, func.sum(
                case(
                    (WatchSession.completed.is_(True), 3),
                    else_=1
                )
            ).label("weight"))
            .select_from(WatchSession)
            .join(VideoTag, VideoTag.video_id == WatchSession.video_id)
            .join(Tag, Tag.id == VideoTag.tag_id)
            .group_by(VideoTag.tag_id, Tag.name)
            .order_by(desc("weight"))
            .limit(10)
        )
        profile_result = await session.execute(profile_stmt)
        top_tags = profile_result.all()
        
        recs = []
        rec_exclude = set(exclude_ids) if exclude_ids else set()
        # Exclude videos that generated the profile (watched videos)
        rec_exclude.update(watched_video_ids)

        if top_tags:
            tag_ids = [t.tag_id for t in top_tags]
            
            # Subquery to calculate shared tag score and get a shared tag name
            tag_score_subq = (
                select(
                    VideoTag.video_id, 
                    func.count().label("tag_score"),
                    func.max(Tag.name).label("shared_tag_name")
                )
                .join(Tag, Tag.id == VideoTag.tag_id)
                .where(VideoTag.tag_id.in_(tag_ids))
                .group_by(VideoTag.video_id)
                .subquery()
            )

            stmt = (
                select(Video, tag_score_subq.c.tag_score, tag_score_subq.c.shared_tag_name)
                .join(tag_score_subq, tag_score_subq.c.video_id == Video.id)
                .where(Video.status != "unavailable")
            )
            if rec_exclude:
                stmt = stmt.where(Video.id.notin_(rec_exclude))
            
            stmt = stmt.order_by(
                tag_score_subq.c.tag_score.desc(),
                Video.watch_count.asc()
            ).limit(rec_limit)
            
            result = await session.execute(stmt)
            scored_videos = result.all()
            
            for video, tag_score, shared_tag_name in scored_videos:
                if shared_tag_name:
                    reason = f"Shared tag: {shared_tag_name}"
                elif video.watch_count == 0:
                    reason = "Unwatched boost"
                else:
                    reason = "Recommended for you"
                    
                recs.append((video, reason))
                rec_exclude.add(video.id)
                
        # Inject 20% random
        random_recs = await RecommendationService.get_random_discovery(session, random_limit, rec_exclude)
        recs.extend(random_recs)
        rec_exclude.update([v.id for v, _ in random_recs])
        
        # Fill the rest with random if we didn't meet the limit
        remaining_limit = limit - len(recs)
        if remaining_limit > 0:
            extra_random_recs = await RecommendationService.get_random_discovery(session, remaining_limit, rec_exclude)
            recs.extend(extra_random_recs)
            
        random.shuffle(recs)
        return recs
