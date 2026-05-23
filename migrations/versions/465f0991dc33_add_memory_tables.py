"""add_memory_tables

Revision ID: 465f0991dc33
Revises: 04931066a40e
Create Date: 2026-05-22 12:16:57.493360

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '465f0991dc33'
down_revision: Union[str, Sequence[str], None] = '04931066a40e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
