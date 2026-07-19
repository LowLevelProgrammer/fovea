from dataclasses import dataclass
from typing import Optional
from uuid import UUID

from sqlalchemy import case, func, select

from app.models.tag import Tag, VideoTag
from app.models.video import Video
from app.models.watch_session import WatchSession


@dataclass(frozen=True)
class RankedVideo:
    video: Video
    reason: str
    score: float


class RecommendationService:
    """Ranks discovery candidates from watch history and library metadata."""

    @staticmethod
    async def get_continue_watching(session, limit: int = 12) -> list[Video]:
        stmt = (
            select(Video)
            .join(WatchSession, WatchSession.video_id == Video.id)
            .where(
                Video.status != "unavailable",
                WatchSession.user_id.is_(None),
                WatchSession.completed.is_(False),
                WatchSession.position_seconds > 0,
            )
            .order_by(WatchSession.updated_at.desc(), Video.id.asc())
            .limit(limit)
        )
        return (await session.execute(stmt)).scalars().all()

    @staticmethod
    async def get_ranked_feed(
        session,
        limit: int = 24,
        offset: int = 0,
        exclude_ids: Optional[set[UUID]] = None,
    ) -> tuple[list[RankedVideo], int]:
        """Return a stable page from one ranked discovery stream.

        Scores combine tag affinity from watch history, watch count, recency,
        and a stable exploration value. Candidates are fully ranked before
        slicing so offsets address one consistent ordered stream.
        """
        excluded = exclude_ids or set()
        stmt = select(Video).where(Video.status != "unavailable")
        if excluded:
            stmt = stmt.where(Video.id.notin_(excluded))
        candidates = (await session.execute(stmt)).scalars().all()

        tag_scores, tag_names = await RecommendationService._watch_tag_profile(session)
        recency_scores, recently_added_ids = RecommendationService._recency_scores(candidates)
        ranked: list[RankedVideo] = []
        for video in candidates:
            tag_score = tag_scores.get(video.id, 0.0)
            popularity_score = min(video.watch_count, 10) * 0.15
            recency_score = recency_scores[video.id]
            exploration_score = (int(video.id.hex[-6:], 16) % 1000) / 10000
            score = tag_score * 3 + popularity_score + recency_score + exploration_score

            if tag_score:
                reason = f"Shared tag: {tag_names[video.id]}"
            elif video.id in recently_added_ids:
                reason = "Recently added"
            elif video.watch_count > 0:
                reason = "Popular in your library"
            else:
                reason = "Random discovery"
            ranked.append(RankedVideo(video=video, reason=reason, score=score))

        ranked.sort(
            key=lambda item: (-item.score, -item.video.added_at.timestamp(), str(item.video.id))
        )
        return ranked[offset : offset + limit], len(ranked)

    @staticmethod
    def _recency_scores(candidates: list[Video]) -> tuple[dict[UUID, float], set[UUID]]:
        """Assign a deterministic recency boost from persisted add order."""
        recent_first = sorted(candidates, key=lambda video: (-video.added_at.timestamp(), str(video.id)))
        candidate_count = len(recent_first)
        if candidate_count == 0:
            return {}, set()

        scores = {
            video.id: 0.75 * (candidate_count - index) / candidate_count
            for index, video in enumerate(recent_first)
        }
        recently_added_ids = {video.id for video in recent_first[: min(12, candidate_count)]}
        return scores, recently_added_ids

    @staticmethod
    async def _watch_tag_profile(session) -> tuple[dict[UUID, float], dict[UUID, str]]:
        profile_stmt = (
            select(
                VideoTag.tag_id,
                func.sum(case((WatchSession.completed.is_(True), 3), else_=1)).label("weight"),
            )
            .select_from(WatchSession)
            .join(VideoTag, VideoTag.video_id == WatchSession.video_id)
            .where(WatchSession.user_id.is_(None))
            .group_by(VideoTag.tag_id)
        )
        profile_rows = (await session.execute(profile_stmt)).all()
        tag_weights = {row.tag_id: float(row.weight) for row in profile_rows}
        if not tag_weights:
            return {}, {}

        candidate_tags_stmt = (
            select(VideoTag.video_id, Tag.name, VideoTag.tag_id)
            .join(Tag, Tag.id == VideoTag.tag_id)
            .where(VideoTag.tag_id.in_(tag_weights))
            .order_by(Tag.name.asc(), VideoTag.video_id.asc())
        )
        scores: dict[UUID, float] = {}
        names: dict[UUID, str] = {}
        for row in (await session.execute(candidate_tags_stmt)).all():
            scores[row.video_id] = scores.get(row.video_id, 0.0) + tag_weights[row.tag_id]
            names.setdefault(row.video_id, row.name)
        return scores, names
