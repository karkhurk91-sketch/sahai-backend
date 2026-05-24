"""add_video_url_to_campaign_creatives

Revision ID: 8fa225cd8e50
Revises: e857770a8370
Create Date: 2026-05-24 13:54:24.599850

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8fa225cd8e50'
down_revision: Union[str, Sequence[str], None] = 'e857770a8370'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add video_url column to campaign_creatives table."""
    # Check if table exists (optional but safe)
    op.add_column('campaign_creatives', sa.Column('video_url', sa.String(500), nullable=True))


def downgrade() -> None:
    """Remove video_url column from campaign_creatives table."""
    op.drop_column('campaign_creatives', 'video_url')