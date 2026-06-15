from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class WatchSessionUpdate(BaseModel):
    """Request schema for updating watch progress."""

    position_seconds: float = Field(..., ge=0.0, description="Current playback position in seconds")
    duration_seconds: Optional[float] = Field(None, ge=0.0, description="Total video duration in seconds")

    @model_validator(mode="after")
    def validate_position_and_duration(self) -> "WatchSessionUpdate":
        if self.duration_seconds is not None and self.position_seconds > self.duration_seconds:
            raise ValueError("position_seconds cannot exceed duration_seconds")
        return self


class WatchSessionRead(BaseModel):
    """Response schema for watch session details."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    video_id: UUID
    user_id: Optional[UUID] = None
    position_seconds: float
    duration_seconds: Optional[float] = None
    completed: bool
    created_at: datetime
    updated_at: datetime
