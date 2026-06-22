"""create_tags_tables

Revision ID: e9995a54737e
Revises: d8885a54737d
Create Date: 2026-06-17 21:15:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e9995a54737e'
down_revision: Union[str, None] = 'd8885a54737d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create tags table (without redundant UniqueConstraint)
    op.create_table(
        'tags',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('name', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    
    # 2. Create case-insensitive unique index on LOWER(name)
    op.create_index(
        'uix_tags_name_lower',
        'tags',
        [sa.text('lower(name)')],
        unique=True
    )

    # 3. Create video_tags join table (with CHECK constraint)
    op.create_table(
        'video_tags',
        sa.Column('video_id', sa.UUID(), nullable=False),
        sa.Column('tag_id', sa.UUID(), nullable=False),
        sa.Column('source', sa.Text(), server_default='manual', nullable=False),
        sa.CheckConstraint("source IN ('manual', 'auto')", name="ck_video_tags_source"),
        sa.ForeignKeyConstraint(['tag_id'], ['tags.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['video_id'], ['videos.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('video_id', 'tag_id')
    )

    # 4. Create index on tag_id for reverse lookups
    op.create_index(
        'ix_video_tags_tag_id',
        'video_tags',
        ['tag_id']
    )


def downgrade() -> None:
    op.drop_index('ix_video_tags_tag_id', table_name='video_tags')
    op.drop_table('video_tags')
    op.drop_index('uix_tags_name_lower', table_name='tags')
    op.drop_table('tags')
