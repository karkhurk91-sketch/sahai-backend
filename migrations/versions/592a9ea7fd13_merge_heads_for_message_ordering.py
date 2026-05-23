"""merge_heads_for_message_ordering

Revision ID: 592a9ea7fd13
Revises: 2026_05_23_msg_order, 393fe506336c
Create Date: 2026-05-23 12:31:29.475171

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '592a9ea7fd13'
down_revision: Union[str, Sequence[str], None] = ('2026_05_23_msg_order', '393fe506336c')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
