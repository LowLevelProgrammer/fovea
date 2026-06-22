from uuid import UUID
from fastapi import APIRouter, HTTPException, status
from sqlalchemy import func, select
from app.api.schemas.tag import TagRead, TagDetails
from app.db.session import async_session
from app.models.tag import Tag, VideoTag
from app.models.video import Video

router = APIRouter(tags=["tags"])


@router.get("", response_model=list[TagRead])
async def list_tags() -> list[TagRead]:
    """
    Retrieve all tags.
    """
    async with async_session() as session:
        result = await session.execute(select(Tag).order_by(Tag.name.asc()))
        tags = result.scalars().all()
    return tags


@router.get("/{tag_id}", response_model=TagDetails)
async def get_tag(tag_id: UUID) -> TagDetails:
    """
    Retrieve detailed tag information including associated video count.
    """
    async with async_session() as session:
        result = await session.execute(select(Tag).where(Tag.id == tag_id))
        tag = result.scalar_one_or_none()
        if not tag:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Tag not found.",
            )

        # Count active associated videos (exclude status='unavailable')
        count_stmt = (
            select(func.count(VideoTag.video_id))
            .join(Video, Video.id == VideoTag.video_id)
            .where(VideoTag.tag_id == tag_id, Video.status != "unavailable")
        )
        count_result = await session.execute(count_stmt)
        video_count = count_result.scalar() or 0

    return TagDetails(
        id=tag.id,
        name=tag.name,
        video_count=video_count,
        created_at=tag.created_at,
        updated_at=tag.updated_at,
    )
