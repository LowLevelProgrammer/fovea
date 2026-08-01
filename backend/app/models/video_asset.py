import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class VideoAsset(Base):
    __tablename__ = "video_assets"
    __table_args__ = (
        UniqueConstraint("video_id", "asset_type", name="uix_video_assets_video_type"),
        Index("ix_video_assets_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    video_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("videos.id", ondelete="CASCADE"), nullable=False
    )
    asset_type: Mapped[str] = mapped_column(Text, nullable=False)
    relative_path: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="pending", server_default="pending")
    generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_file_mtime: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_file_size: Mapped[int | None] = mapped_column(BigInteger)
    generation_mode: Mapped[str] = mapped_column(Text, nullable=False, default="automatic", server_default="automatic")
    metadata_json: Mapped[dict | None] = mapped_column(JSONB)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
