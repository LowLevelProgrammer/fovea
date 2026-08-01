from app.api.schemas.watch_path import WatchPathCreate, WatchPathRead, WatchPathUpdate
from app.api.schemas.video import (
    ScanResultResponse,
    SimilarVideoItem,
    SimilarVideosResponse,
    ThumbnailRequest,
    ThumbnailRequestResponse,
    VideoListItem,
    VideoListResponse,
    VideoRead,
)
from app.api.schemas.watch_session import WatchSessionUpdate, WatchSessionRead
from app.api.schemas.tag import TagRead, TagDetails, VideoTagUpdate
from app.api.schemas.feed import FeedResponse

__all__ = [
    "WatchPathCreate",
    "WatchPathRead",
    "WatchPathUpdate",
    "VideoRead",
    "VideoListItem",
    "ScanResultResponse",
    "VideoListResponse",
    "SimilarVideoItem",
    "SimilarVideosResponse",
    "ThumbnailRequest",
    "ThumbnailRequestResponse",
    "WatchSessionUpdate",
    "WatchSessionRead",
    "TagRead",
    "TagDetails",
    "VideoTagUpdate",
    "FeedResponse",
]
