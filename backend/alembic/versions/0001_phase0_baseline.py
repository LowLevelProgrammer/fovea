"""phase 0 baseline

Revision ID: 0001_phase0_baseline
Revises:
Create Date: 2026-06-07

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0001_phase0_baseline"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "watch_paths",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("scan_recursive", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("label", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("path"),
    )

    op.create_table(
        "videos",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("file_path", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("title_override", sa.Text(), nullable=True),
        sa.Column("file_size", sa.BigInteger(), nullable=False),
        sa.Column("file_mtime", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fingerprint", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), server_default="discovered", nullable=False),
        sa.Column("added_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("unavailable_since", sa.DateTime(timezone=True), nullable=True),
        sa.Column("watch_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_watched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("file_path"),
    )
    op.create_index("idx_videos_status", "videos", ["status"])
    op.create_index("idx_videos_added_at", "videos", [sa.text("added_at DESC")])
    op.create_index("idx_videos_last_watched", "videos", [sa.text("last_watched_at DESC NULLS LAST")])
    op.create_index("idx_videos_watch_count", "videos", [sa.text("watch_count DESC")])
    op.create_index(
        "idx_videos_path_prefix",
        "videos",
        ["file_path"],
        postgresql_ops={"file_path": "text_pattern_ops"},
    )


def downgrade() -> None:
    op.drop_index("idx_videos_path_prefix", table_name="videos")
    op.drop_index("idx_videos_watch_count", table_name="videos")
    op.drop_index("idx_videos_last_watched", table_name="videos")
    op.drop_index("idx_videos_added_at", table_name="videos")
    op.drop_index("idx_videos_status", table_name="videos")
    op.drop_table("videos")
    op.drop_table("watch_paths")
