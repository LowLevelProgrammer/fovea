"""create video assets

Revision ID: f3b4c5d6e7f8
Revises: f2a1b3c4d5e6
Create Date: 2026-07-20 10:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "f3b4c5d6e7f8"
down_revision: Union[str, None] = "f2a1b3c4d5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "video_assets",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("video_id", sa.UUID(), nullable=False),
        sa.Column("asset_type", sa.Text(), nullable=False),
        sa.Column("relative_path", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), server_default="pending", nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_file_mtime", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_file_size", sa.BigInteger(), nullable=True),
        sa.Column("generation_mode", sa.Text(), server_default="automatic", nullable=False),
        sa.Column("metadata_json", postgresql.JSONB(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["video_id"], ["videos.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("video_id", "asset_type", name="uix_video_assets_video_type"),
    )
    op.create_index("ix_video_assets_status", "video_assets", ["status"])


def downgrade() -> None:
    op.drop_index("ix_video_assets_status", table_name="video_assets")
    op.drop_table("video_assets")
