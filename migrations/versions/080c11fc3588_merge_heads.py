"""merge heads

Revision ID: 080c11fc3588
Revises: 37b5237b9ac9_phase2, add_facebook_boosts_c80b6d33
Create Date: 2026-06-14 18:08:47.118530

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '080c11fc3588'
down_revision: Union[str, Sequence[str], None] = ('37b5237b9ac9_phase2', 'add_facebook_boosts_c80b6d33')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
