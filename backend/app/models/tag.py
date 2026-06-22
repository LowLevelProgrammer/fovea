import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Text, func, CheckConstraint, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class VideoTag(Base):
    __tablename__ = "video_tags"
    __table_args__ = (
        CheckConstraint("source IN ('manual', 'auto')", name="ck_video_tags_source"),
    )

    video_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("videos.id", ondelete="CASCADE"), primary_key=True
    )
    tag_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    source: Mapped[str] = mapped_column(
        Text, nullable=False, default="manual", server_default="manual"
    )

    # Relationships back to Video and Tag
    video: Mapped["Video"] = relationship("Video", back_populates="video_tags_association")
    tag: Mapped["Tag"] = relationship("Tag", back_populates="video_tags_association")


class Tag(Base):
    __tablename__ = "tags"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    # Relationship to VideoTag association table
    video_tags_association: Mapped[list[VideoTag]] = relationship(
        VideoTag, back_populates="tag", cascade="all, delete-orphan"
    )

    # Many-to-many relationship with Video (viewonly for simple reading)
    videos: Mapped[list["Video"]] = relationship(
        "Video",
        secondary="video_tags",
        back_populates="tags",
        viewonly=True,
    )

    __table_args__ = (
        Index("uix_tags_name_lower", func.lower(name), unique=True),
    )
