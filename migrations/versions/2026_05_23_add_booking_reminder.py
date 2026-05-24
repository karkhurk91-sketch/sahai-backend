"""add_booking_reminder_column

Revision ID: 2026_05_23_booking_reminder
Revises: 2026_05_23_msg_order
Create Date: 2026-05-23 12:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "2026_05_23_booking_reminder"
down_revision: Union[str, Sequence[str], None] = "2026_05_23_msg_order"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "bookings",
        sa.Column(
            "reminder_sent",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("bookings", "reminder_sent")