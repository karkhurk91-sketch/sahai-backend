"""merge heads

Revision ID: e857770a8370
Revises: 2026_05_24_booking_lead_id, e9a91a1947c0
Create Date: 2026-05-24 08:06:22.293042

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e857770a8370'
down_revision: Union[str, Sequence[str], None] = ('2026_05_24_booking_lead_id', 'e9a91a1947c0')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
