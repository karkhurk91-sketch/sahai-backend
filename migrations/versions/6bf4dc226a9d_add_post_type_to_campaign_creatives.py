"""add_post_type_to_campaign_creatives

Revision ID: 6bf4dc226a9d
Revises: 8fa225cd8e50
Create Date: 2026-05-24 14:15:26.886555

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6bf4dc226a9d'
down_revision: Union[str, Sequence[str], None] = '8fa225cd8e50'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('campaigns', sa.Column('post_type', sa.String(20), server_default='ai', nullable=False))
    pass


def downgrade() -> None:
    op.drop_column('campaigns', 'post_type')
    pass
