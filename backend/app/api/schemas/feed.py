from pydantic import BaseModel
from app.api.schemas.video import VideoListItem

class RankedFeedPage(BaseModel):
    items: list[VideoListItem]
    offset: int
    limit: int
    total: int
    has_more: bool

class FeedResponse(BaseModel):
    continue_watching: list[VideoListItem]
    recommendations: RankedFeedPage
