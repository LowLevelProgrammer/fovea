from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status, Header
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select, or_, case, exists
from sqlalchemy.orm import selectinload

from app.api.schemas.video import ScanResultResponse, VideoListResponse, VideoListItem, VideoRead
from app.api.schemas.tag import VideoTagUpdate
from app.db.session import async_session
from app.models.video import Video
from app.models.tag import Tag, VideoTag
from app.services.scan_service import ScanService
from app.core.range_stream import range_stream_response

router = APIRouter(tags=["videos"])


@router.post("/library/scan", response_model=ScanResultResponse, status_code=status.HTTP_202_ACCEPTED)
async def trigger_scan(watch_path_id: UUID | None = None) -> ScanResultResponse:
    """
    Trigger a manual scan of watch paths.

    Query params:
    - watch_path_id (optional): UUID of a specific watch path to scan. If omitted, all enabled paths are scanned.

    Response: 202 Accepted with scan result summary
    """
    try:
        result = await ScanService.scan(watch_path_id)
        return ScanResultResponse(
            watch_paths_scanned=result.watch_paths_scanned,
            videos_discovered=result.videos_discovered,
            videos_unavailable=result.videos_unavailable,
            duration_seconds=result.duration_seconds,
            started_at=result.started_at,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )
    except (FileNotFoundError, PermissionError) as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except RuntimeError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@router.get("/videos", response_model=VideoListResponse)
async def list_videos(
    page: int = Query(1, ge=1),
    limit: int = Query(24, ge=1, le=100),
    status: str | None = None,
) -> VideoListResponse:
    """
    List all discovered videos with optional filtering.

    Query params:
    - page (int): Page number, starting at 1 (default 1)
    - limit (int): Items per page, 1-100 (default 24)
    - status (str, optional): Filter by status (e.g., 'discovered', 'ready')

    Response: Paginated list of videos
    """
    async with async_session() as session:
        # Build query (exclude unavailable videos)
        query = select(Video).where(Video.status != "unavailable")
        if status:
            query = query.where(Video.status == status)

        # Get total count (exclude unavailable videos)
        count_query = select(func.count(Video.id)).where(Video.status != "unavailable")
        if status:
            count_query = count_query.where(Video.status == status)
        total_result = await session.execute(count_query)
        total = total_result.scalar() or 0

        # Apply pagination
        offset = (page - 1) * limit
        query = query.order_by(Video.added_at.desc()).offset(offset).limit(limit)

        result = await session.execute(query)
        videos = result.scalars().all()

    items = [VideoListItem.model_validate(v) for v in videos]
    has_more = (page * limit) < total

    return VideoListResponse(
        items=items,
        page=page,
        limit=limit,
        total=total,
        has_more=has_more,
    )


@router.get("/videos/{video_id}", response_model=VideoRead)
async def get_video(video_id: UUID) -> VideoRead:
    """
    Retrieve detailed information for a single video.

    Path params:
    - video_id (UUID): ID of the video

    Response: Full video record
    Errors: 404 if not found
    """
    from app.models.watch_session import WatchSession

    async with async_session() as session:
        result = await session.execute(
            select(Video).options(selectinload(Video.tags)).where(Video.id == video_id)
        )
        video = result.scalar_one_or_none()

        if not video:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Video not found.",
            )

        # Query watch progress session for resume position
        session_result = await session.execute(
            select(WatchSession).where(
                WatchSession.video_id == video_id, WatchSession.user_id.is_(None)
            )
        )
        watch_session = session_result.scalar_one_or_none()
        resume_pos = None
        if watch_session and not watch_session.completed:
                resume_pos = watch_session.position_seconds

    video_read = VideoRead.model_validate(video)
    video_read.resume_position_seconds = resume_pos
    return video_read


@router.get("/videos/{video_id}/stream")
async def stream_video(
    video_id: UUID,
    range: str | None = Header(None, alias="Range"),
) -> StreamingResponse:
    """
    Stream video source file with HTTP Range support.

    Path params:
    - video_id (UUID): ID of the video

    Headers:
    - Range (optional): Byte range request header (e.g., 'bytes=0-1000')
    """
    async with async_session() as session:
        result = await session.execute(select(Video).where(Video.id == video_id))
        video = result.scalar_one_or_none()

    if not video:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Video not found.",
        )

    if video.status == "unavailable":
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="Video is unavailable.",
        )

    return range_stream_response(video.file_path, range)


@router.get("/search", response_model=list[VideoListItem])
async def search_videos(q: str = Query(..., min_length=1)) -> list[VideoListItem]:
    """
    Search videos by title, title_override, filename, or associated tags case-insensitively.
    Orders by basic relevance (title_override match first, then title, then tag match, then filename).
    """
    search_pattern = f"%{q.lower()}%"
    has_tag_match = (
        select(1)
        .select_from(VideoTag)
        .join(Tag, Tag.id == VideoTag.tag_id)
        .where(
            VideoTag.video_id == Video.id,
            func.lower(Tag.name).like(search_pattern)
        )
        .exists()
    )
    score = case(
        (func.lower(Video.title_override).like(search_pattern), 4),
        (func.lower(Video.title).like(search_pattern), 3),
        (has_tag_match, 2),
        (func.lower(Video.file_path).like(search_pattern), 1),
        else_=0
    )

    async with async_session() as session:
        stmt = (
            select(Video)
            .where(Video.status != "unavailable", score > 0)
            .order_by(score.desc(), Video.title.asc())
        )
        result = await session.execute(stmt)
        videos = result.scalars().all()

    items = [VideoListItem.model_validate(v) for v in videos]
    return items



@router.patch("/videos/{video_id}", response_model=VideoRead)
async def update_video_tags(video_id: UUID, payload: VideoTagUpdate) -> VideoRead:
    """
    Assign or remove tags for a video manually.
    """
    from app.models.watch_session import WatchSession

    async with async_session() as session:
        result = await session.execute(
            select(Video).options(selectinload(Video.tags)).where(Video.id == video_id)
        )
        video = result.scalar_one_or_none()
        if not video:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Video not found.",
            )

        target_tags = []
        for tag_name in payload.tags:
            tag_name_clean = tag_name.strip()
            if not tag_name_clean:
                continue

            tag_stmt = select(Tag).where(func.lower(Tag.name) == tag_name_clean.lower())
            tag_result = await session.execute(tag_stmt)
            tag = tag_result.scalar_one_or_none()

            if not tag:
                tag = Tag(name=tag_name_clean)
                session.add(tag)
                await session.flush()

            if tag not in target_tags:
                target_tags.append(tag)

        assoc_stmt = select(VideoTag).where(VideoTag.video_id == video_id)
        assoc_result = await session.execute(assoc_stmt)
        existing_assocs = assoc_result.scalars().all()

        target_tag_ids = {tag.id for tag in target_tags}
        existing_assoc_by_tag_id = {assoc.tag_id: assoc for assoc in existing_assocs}

        for tag_id, assoc in list(existing_assoc_by_tag_id.items()):
            if tag_id in target_tag_ids:
                if assoc.source != "manual":
                    assoc.source = "manual"
                    session.add(assoc)
            else:
                if assoc.source == "manual":
                    await session.delete(assoc)

        for tag in target_tags:
            if tag.id not in existing_assoc_by_tag_id:
                new_assoc = VideoTag(video_id=video_id, tag_id=tag.id, source="manual")
                session.add(new_assoc)

        await session.commit()

        session_result = await session.execute(
            select(WatchSession).where(
                WatchSession.video_id == video_id, WatchSession.user_id.is_(None)
            )
        )
        watch_session = session_result.scalar_one_or_none()
        resume_pos = None
        if watch_session and not watch_session.completed:
            resume_pos = watch_session.position_seconds

        await session.refresh(video)

    video_read = VideoRead.model_validate(video)
    video_read.resume_position_seconds = resume_pos
    return video_read


