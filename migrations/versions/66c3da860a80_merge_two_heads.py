"""merge two heads

Revision ID: 66c3da860a80
Revises: 2026_05_26_001, 5c7d47c6a512
Create Date: 2026-05-26 20:26:48.670434

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '66c3da860a80'
down_revision: Union[str, Sequence[str], None] = ('2026_05_26_001', '5c7d47c6a512')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
