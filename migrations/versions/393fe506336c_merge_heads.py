"""merge_heads

Revision ID: 393fe506336c
Revises: 0c0600ec9a08, 465f0991dc33
Create Date: 2026-05-22 12:20:22.627179

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '393fe506336c'
down_revision: Union[str, Sequence[str], None] = ('0c0600ec9a08', '465f0991dc33')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
