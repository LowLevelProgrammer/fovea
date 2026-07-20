"""create search history

Revision ID: f2a1b3c4d5e6
Revises: e9995a54737e
Create Date: 2026-07-19 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f2a1b3c4d5e6"
down_revision: Union[str, None] = "e9995a54737e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "search_history",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("searched_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("result_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("clicked_video_id", sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(["clicked_video_id"], ["videos.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_search_history_searched_at", "search_history", [sa.text("searched_at DESC")])


def downgrade() -> None:
    op.drop_index("ix_search_history_searched_at", table_name="search_history")
    op.drop_table("search_history")
