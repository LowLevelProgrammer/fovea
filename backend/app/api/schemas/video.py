from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from app.api.schemas.tag import TagRead


class VideoRead(BaseModel):
    """Complete video record."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    file_path: str
    title: str
    title_override: Optional[str] = None
    file_size: int
    file_mtime: datetime
    fingerprint: Optional[str] = None
    status: str
    added_at: datetime
    last_seen_at: datetime
    unavailable_since: Optional[datetime] = None
    watch_count: int
    last_watched_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    resume_position_seconds: Optional[float] = None
    tags: list[TagRead] = Field(default_factory=list)



class VideoListItem(BaseModel):
    """Lightweight video summary for list endpoints."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    file_path: str
    title: str
    file_size: int
    status: str
    added_at: datetime
    last_seen_at: datetime
    recommendation_reason: Optional[str] = None


class ScanResultResponse(BaseModel):
    """Response from a scan operation."""

    watch_paths_scanned: int
    videos_discovered: int
    videos_unavailable: int
    duration_seconds: float
    started_at: datetime


class VideoListResponse(BaseModel):
    """Paginated list of videos."""

    items: list[VideoListItem]
    page: int
    limit: int
    total: int
    has_more: bool
