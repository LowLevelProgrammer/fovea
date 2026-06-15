import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class WatchSession(Base):
    __tablename__ = "watch_sessions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    video_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("videos.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    position_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    completed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
        onupdate=text("now()"),
    )

    # Relationships
    video = relationship("Video", backref="watch_sessions")

    # Table arguments to enforce unique session per (video_id, user_id)
    # Since user_id is nullable, we use a partial index for the NULL case,
    # and a standard unique index for the non-NULL case.
    __table_args__ = (
        Index(
            "uix_watch_sessions_video_user",
            "video_id",
            "user_id",
            unique=True,
            postgresql_where=text("user_id IS NOT NULL"),
        ),
        Index(
            "uix_watch_sessions_video_user_null",
            "video_id",
            unique=True,
            postgresql_where=text("user_id IS NULL"),
        ),
    )
