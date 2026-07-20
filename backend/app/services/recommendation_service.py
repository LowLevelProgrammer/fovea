from dataclasses import dataclass
from typing import Optional
from uuid import UUID

from sqlalchemy import select

from app.models.search_history import SearchHistory
from app.models.tag import Tag, VideoTag
from app.models.video import Video
from app.models.watch_session import WatchSession
from app.services.tokenization import tokenize


WATCHED_TITLE_WEIGHT = 2.0
TAG_WEIGHT = 3.0
MANUAL_TAG_MULTIPLIER = 1.25
SEARCH_WEIGHT = 0.4
SEARCH_HISTORY_LIMIT = 50
WATCH_HISTORY_LIMIT = 200


@dataclass(frozen=True)
class RankedVideo:
    video: Video
    reason: str
    score: float


@dataclass(frozen=True)
class WatchedVideo:
    video_id: UUID
    title: str
    completed: bool


class RecommendationService:
    """Ranks discovery candidates from deterministic user-interest signals."""

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
        excluded = exclude_ids or set()
        candidates_stmt = select(Video).where(Video.status != "unavailable")
        if excluded:
            candidates_stmt = candidates_stmt.where(Video.id.notin_(excluded))
        candidates = (await session.execute(candidates_stmt)).scalars().all()

        watched_history = await RecommendationService._recent_watch_history(session)
        tag_scores, tag_names = await RecommendationService._watch_tag_profile(session, watched_history)
        watched_keyword_scores, watched_keywords = RecommendationService._watched_title_profile(
            watched_history, candidates
        )
        search_scores, search_terms = await RecommendationService._search_title_profile(session, candidates)
        recency_scores, recently_added_ids = RecommendationService._recency_scores(candidates)

        ranked = [
            RecommendationService._rank_candidate(
                video,
                tag_scores,
                tag_names,
                watched_keyword_scores,
                watched_keywords,
                search_scores,
                search_terms,
                recency_scores,
                recently_added_ids,
            )
            for video in candidates
        ]
        ranked.sort(
            key=lambda item: (-item.score, -item.video.added_at.timestamp(), str(item.video.id))
        )
        return ranked[offset : offset + limit], len(ranked)

    @staticmethod
    def _rank_candidate(
        video: Video,
        tag_scores: dict[UUID, float],
        tag_names: dict[UUID, str],
        watched_keyword_scores: dict[UUID, float],
        watched_keywords: dict[UUID, str],
        search_scores: dict[UUID, float],
        search_terms: dict[UUID, str],
        recency_scores: dict[UUID, float],
        recently_added_ids: set[UUID],
    ) -> RankedVideo:
        tag_contribution = tag_scores.get(video.id, 0.0) * TAG_WEIGHT
        watched_keyword_contribution = watched_keyword_scores.get(video.id, 0.0) * WATCHED_TITLE_WEIGHT
        search_contribution = search_scores.get(video.id, 0.0) * SEARCH_WEIGHT
        popularity_contribution = min(video.watch_count, 10) * 0.15
        recency_contribution = recency_scores[video.id]
        exploration_contribution = (int(video.id.hex[-6:], 16) % 1000) / 10000
        score = (
            tag_contribution
            + watched_keyword_contribution
            + search_contribution
            + popularity_contribution
            + recency_contribution
            + exploration_contribution
        )

        if tag_contribution > 0 and tag_contribution >= watched_keyword_contribution and tag_contribution >= search_contribution:
            reason = f"Shared tag: {tag_names[video.id]}"
        elif watched_keyword_contribution > 0 and watched_keyword_contribution >= search_contribution:
            reason = f"Shared keyword: {watched_keywords[video.id]}"
        elif search_contribution > 0:
            reason = f"Because you searched: {search_terms[video.id]}"
        elif video.id in recently_added_ids:
            reason = "Recently added"
        elif video.watch_count > 0:
            reason = "Popular in your library"
        else:
            reason = "Random discovery"
        return RankedVideo(video=video, reason=reason, score=score)

    @staticmethod
    def _watched_title_profile(
        watched_history: list[WatchedVideo], candidates: list[Video]
    ) -> tuple[dict[UUID, float], dict[UUID, str]]:
        token_weights: dict[str, float] = {}
        for watched in watched_history:
            watch_weight = 3.0 if watched.completed else 1.0
            for token in tokenize(watched.title):
                token_weights[token] = token_weights.get(token, 0.0) + watch_weight
        return RecommendationService._title_overlap_scores(candidates, token_weights)

    @staticmethod
    async def _recent_watch_history(session) -> list[WatchedVideo]:
        rows = await session.execute(
            select(Video.id, Video.title, WatchSession.completed)
            .join(WatchSession, WatchSession.video_id == Video.id)
            .where(WatchSession.user_id.is_(None))
            .order_by(WatchSession.updated_at.desc(), Video.id.asc())
            .limit(WATCH_HISTORY_LIMIT)
        )
        return [WatchedVideo(video_id=row.id, title=row.title, completed=row.completed) for row in rows.all()]

    @staticmethod
    async def _search_title_profile(
        session, candidates: list[Video]
    ) -> tuple[dict[UUID, float], dict[UUID, str]]:
        history = (
            await session.execute(
                select(SearchHistory)
                .order_by(SearchHistory.searched_at.desc(), SearchHistory.id.asc())
                .limit(SEARCH_HISTORY_LIMIT)
            )
        ).scalars().all()
        token_weights: dict[str, float] = {}
        history_count = len(history)
        for index, entry in enumerate(history):
            recency_weight = 1 + (history_count - index) / history_count
            for token in tokenize(entry.query):
                token_weights[token] = token_weights.get(token, 0.0) + recency_weight
        return RecommendationService._title_overlap_scores(candidates, token_weights)

    @staticmethod
    def _title_overlap_scores(
        candidates: list[Video], token_weights: dict[str, float]
    ) -> tuple[dict[UUID, float], dict[UUID, str]]:
        scores: dict[UUID, float] = {}
        strongest_terms: dict[UUID, str] = {}
        for video in candidates:
            matched = tokenize(video.title).intersection(token_weights)
            if matched:
                scores[video.id] = sum(token_weights[token] for token in matched)
                strongest_terms[video.id] = min(matched, key=lambda token: (-token_weights[token], token))
        return scores, strongest_terms

    @staticmethod
    def _recency_scores(candidates: list[Video]) -> tuple[dict[UUID, float], set[UUID]]:
        recent_first = sorted(candidates, key=lambda video: (-video.added_at.timestamp(), str(video.id)))
        candidate_count = len(recent_first)
        if candidate_count == 0:
            return {}, set()
        scores = {
            video.id: 0.75 * (candidate_count - index) / candidate_count
            for index, video in enumerate(recent_first)
        }
        return scores, {video.id for video in recent_first[: min(12, candidate_count)]}

    @staticmethod
    async def _watch_tag_profile(
        session, watched_history: list[WatchedVideo]
    ) -> tuple[dict[UUID, float], dict[UUID, str]]:
        completed_by_video_id = {watched.video_id: watched.completed for watched in watched_history}
        if not completed_by_video_id:
            return {}, {}
        watched_tags = await session.execute(
            select(VideoTag.video_id, VideoTag.tag_id, VideoTag.source).where(
                VideoTag.video_id.in_(completed_by_video_id)
            )
        )
        tag_weights: dict[UUID, float] = {}
        for row in watched_tags.all():
            watch_weight = 3.0 if completed_by_video_id[row.video_id] else 1.0
            source_weight = MANUAL_TAG_MULTIPLIER if row.source == "manual" else 1.0
            tag_weights[row.tag_id] = tag_weights.get(row.tag_id, 0.0) + watch_weight * source_weight
        if not tag_weights:
            return {}, {}

        candidate_tags = await session.execute(
            select(VideoTag.video_id, Tag.name, VideoTag.tag_id)
            .join(Tag, Tag.id == VideoTag.tag_id)
            .where(VideoTag.tag_id.in_(tag_weights))
            .order_by(Tag.name.asc(), VideoTag.video_id.asc())
        )
        scores: dict[UUID, float] = {}
        names: dict[UUID, str] = {}
        for row in candidate_tags.all():
            scores[row.video_id] = scores.get(row.video_id, 0.0) + tag_weights[row.tag_id]
            names.setdefault(row.video_id, row.name)
        return scores, names
