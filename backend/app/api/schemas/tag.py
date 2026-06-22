from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, ConfigDict


class TagRead(BaseModel):
    id: UUID
    name: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TagDetails(BaseModel):
    id: UUID
    name: str
    video_count: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class VideoTagUpdate(BaseModel):
    tags: list[str]
