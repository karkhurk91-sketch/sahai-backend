"""merge heads

Revision ID: 5c7d47c6a512
Revises: 2026_05_25_state_machine, e857770a8370
Create Date: 2026-05-26 18:31:56.728107

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5c7d47c6a512'
down_revision: Union[str, Sequence[str], None] = ('2026_05_25_state_machine', 'e857770a8370')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
