import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.models.search_history import SearchHistory
from app.models.video import Video
from app.models.watch_session import WatchSession
from app.services.recommendation_service import RecommendationService
from app.services.tokenization import tokenize


def make_video(now: datetime, title: str) -> Video:
    return Video(
        id=uuid.uuid4(),
        file_path=f"/media/{uuid.uuid4()}.mp4",
        title=title,
        file_size=1024,
        file_mtime=now,
        status="ready",
        added_at=now,
        last_seen_at=now,
    )


def test_tokenize_filters_configured_stop_words():
    assert tokenize("How to Learn the Linux Kernel Using This Video") == {"linux", "kernel"}


@pytest.mark.anyio
async def test_watched_title_keywords_rank_candidates_and_explain_reason(db_session):
    now = datetime.now(timezone.utc)
    watched = make_video(now, "Linux Kernel Internals Guide")
    keyword_match = make_video(now, "Linux Kernel Scheduling")
    unrelated = make_video(now, "Football Highlights")
    db_session.add_all([watched, keyword_match, unrelated])
    await db_session.flush()
    db_session.add(
        WatchSession(
            id=uuid.uuid4(),
            video_id=watched.id,
            user_id=None,
            position_seconds=600,
            duration_seconds=600,
            completed=True,
        )
    )
    await db_session.commit()

    ranked, _ = await RecommendationService.get_ranked_feed(
        db_session, exclude_ids={watched.id}, limit=2
    )
    assert ranked[0].video.id == keyword_match.id
    assert ranked[0].reason == "Shared keyword: kernel"


@pytest.mark.anyio
async def test_search_profile_uses_only_the_most_recent_history_window(db_session):
    now = datetime.now(timezone.utc)
    legacy_match = make_video(now, "Legacy Topic Overview")
    current_match = make_video(now, "Current Topic Overview")
    db_session.add_all([legacy_match, current_match])
    await db_session.flush()
    db_session.add(SearchHistory(query="legacy", searched_at=now - timedelta(days=365)))
    db_session.add_all(
        SearchHistory(query="current", searched_at=now - timedelta(seconds=index))
        for index in range(50)
    )
    await db_session.commit()

    scores, terms = await RecommendationService._search_title_profile(
        db_session, [legacy_match, current_match]
    )
    assert legacy_match.id not in scores
    assert scores[current_match.id] > 0
    assert terms[current_match.id] == "current"
