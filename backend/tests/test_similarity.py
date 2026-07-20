import uuid
from datetime import datetime, timezone

import pytest

from app.models.tag import Tag, VideoTag
from app.models.video import Video
from app.models.video_probe import VideoProbe


def video(now, path: str, title: str) -> Video:
    return Video(
        id=uuid.uuid4(),
        file_path=path,
        title=title,
        file_size=1024,
        file_mtime=now,
        status="ready",
        added_at=now,
        last_seen_at=now,
    )


@pytest.mark.anyio
async def test_similar_videos_are_ranked_stably_and_paginated(db_session, client):
    now = datetime.now(timezone.utc)
    source = video(now, "/media/programming/dynamic-programming-intro.mp4", "Dynamic Programming Introduction")
    strongest_match = video(now, "/media/programming/dynamic-programming-memoization.mp4", "Dynamic Programming Memoization")
    tag_match = video(now, "/media/other/algorithm-notes.mp4", "Algorithm Notes")
    unrelated = video(now, "/media/music/live-set.mp4", "Live Music Set")
    algorithm = Tag(name="Algorithms")
    dynamic = Tag(name="Dynamic Programming")
    db_session.add_all([source, strongest_match, tag_match, unrelated, algorithm, dynamic])
    await db_session.flush()
    db_session.add_all([
        VideoTag(video_id=source.id, tag_id=algorithm.id, source="auto"),
        VideoTag(video_id=source.id, tag_id=dynamic.id, source="auto"),
        VideoTag(video_id=strongest_match.id, tag_id=algorithm.id, source="auto"),
        VideoTag(video_id=strongest_match.id, tag_id=dynamic.id, source="auto"),
        VideoTag(video_id=tag_match.id, tag_id=algorithm.id, source="auto"),
        VideoProbe(video_id=source.id, duration_seconds=600.0),
        VideoProbe(video_id=strongest_match.id, duration_seconds=620.0),
    ])
    await db_session.commit()

    first = await client.get(f"/api/v1/videos/{source.id}/similar?offset=0&limit=1")
    repeated = await client.get(f"/api/v1/videos/{source.id}/similar?offset=0&limit=1")
    second = await client.get(f"/api/v1/videos/{source.id}/similar?offset=1&limit=1")
    assert first.status_code == 200
    first_data = first.json()
    assert first_data["total"] == 2
    assert first_data["items"][0]["id"] == str(strongest_match.id)
    assert first_data["items"][0]["similarity_reason"] == "Multiple shared tags"
    assert first_data["items"][0]["id"] != str(source.id)
    assert first_data["items"] == repeated.json()["items"]
    assert first_data["items"][0]["id"] != second.json()["items"][0]["id"]
