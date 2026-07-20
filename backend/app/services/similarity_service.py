from dataclasses import dataclass
from pathlib import PurePath
import re
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.models.video import Video
from app.models.video_probe import VideoProbe


@dataclass(frozen=True)
class SimilarVideo:
    video: Video
    reason: str
    score: float


class SimilarityService:
    """Ranks videos by metadata similarity, independent of user activity."""

    @staticmethod
    async def get_similar(
        session, source: Video, limit: int = 12, offset: int = 0
    ) -> tuple[list[SimilarVideo], int]:
        candidates = (
            await session.execute(
                select(Video)
                .options(selectinload(Video.tags))
                .where(Video.status != "unavailable", Video.id != source.id)
            )
        ).scalars().all()

        durations = await SimilarityService._duration_map(
            session, [source.id, *(video.id for video in candidates)]
        )
        source_tags = {tag.name for tag in source.tags}
        source_title_tokens = SimilarityService._tokenize(source.title)
        source_filename_tokens = SimilarityService._tokenize(PurePath(source.file_path).stem)
        source_parent = PurePath(source.file_path).parent

        ranked: list[SimilarVideo] = []
        for candidate in candidates:
            shared_tags = sorted(source_tags.intersection(tag.name for tag in candidate.tags))
            title_overlap = source_title_tokens.intersection(SimilarityService._tokenize(candidate.title))
            filename_overlap = source_filename_tokens.intersection(
                SimilarityService._tokenize(PurePath(candidate.file_path).stem)
            )
            same_folder = source_parent == PurePath(candidate.file_path).parent
            duration_score = SimilarityService._duration_score(
                durations.get(source.id), durations.get(candidate.id)
            )

            score = (
                len(shared_tags) * 4.0
                + len(title_overlap) * 2.5
                + len(filename_overlap) * 1.0
                + (1.5 if same_folder else 0.0)
                + duration_score
            )
            if score == 0:
                continue

            if len(shared_tags) > 1:
                reason = "Multiple shared tags"
            elif shared_tags:
                reason = f"Shared tag: {shared_tags[0]}"
            elif title_overlap:
                reason = "Similar title"
            elif filename_overlap:
                reason = "Similar filename"
            elif same_folder:
                reason = "Same folder"
            else:
                reason = "Similar duration"
            ranked.append(SimilarVideo(video=candidate, reason=reason, score=score))

        ranked.sort(
            key=lambda item: (-item.score, -item.video.added_at.timestamp(), str(item.video.id))
        )
        return ranked[offset : offset + limit], len(ranked)

    @staticmethod
    def _tokenize(text: str) -> set[str]:
        ignored_tokens = {"and", "for", "from", "the", "video", "with"}
        return {
            token
            for token in re.findall(r"[a-z0-9]+", text.lower())
            if len(token) > 1 and token not in ignored_tokens
        }

    @staticmethod
    async def _duration_map(session, video_ids: list[UUID]) -> dict[UUID, float]:
        rows = await session.execute(
            select(VideoProbe.video_id, VideoProbe.duration_seconds).where(VideoProbe.video_id.in_(video_ids))
        )
        return {
            row.video_id: row.duration_seconds
            for row in rows.all()
            if row.duration_seconds is not None and row.duration_seconds > 0
        }

    @staticmethod
    def _duration_score(source_duration: float | None, candidate_duration: float | None) -> float:
        if not source_duration or not candidate_duration:
            return 0.0
        difference = abs(source_duration - candidate_duration) / max(source_duration, candidate_duration)
        if difference <= 0.1:
            return 0.5
        if difference <= 0.25:
            return 0.2
        return 0.0
