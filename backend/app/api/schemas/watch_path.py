from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class WatchPathBase(BaseModel):
    path: str = Field(..., description="Container-canonical absolute watch path")
    label: Optional[str] = Field(None, description="User-provided label for the watch path")
    scan_recursive: Optional[bool] = Field(
        True,
        description="Whether the watcher should scan subdirectories recursively",
    )


class WatchPathCreate(WatchPathBase):
    pass


class WatchPathUpdate(BaseModel):
    enabled: Optional[bool] = Field(None, description="Enable or disable the watch path")
    label: Optional[str] = Field(
        None,
        description="User-friendly label for the watch path; null clears it",
    )
    scan_recursive: Optional[bool] = Field(
        None,
        description="Whether the watcher should scan subdirectories recursively",
    )


class WatchPathRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    path: str
    enabled: bool
    scan_recursive: bool
    label: Optional[str]
    created_at: datetime
    updated_at: datetime
