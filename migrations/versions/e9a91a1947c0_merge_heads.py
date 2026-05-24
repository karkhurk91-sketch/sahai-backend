"""merge_heads

Revision ID: e9a91a1947c0
Revises: 2026_05_23_booking_reminder, 592a9ea7fd13
Create Date: 2026-05-23 18:16:11.484084

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e9a91a1947c0'
down_revision: Union[str, Sequence[str], None] = ('2026_05_23_booking_reminder', '592a9ea7fd13')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
