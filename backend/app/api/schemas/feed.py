from typing import Literal
from pydantic import BaseModel
from app.api.schemas.video import VideoListItem

class FeedSection(BaseModel):
    id: str
    title: str
    type: Literal["recently_added", "continue_watching", "tag", "recommended"]
    items: list[VideoListItem]

class FeedResponse(BaseModel):
    sections: list[FeedSection]
