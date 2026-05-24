"""add_booking_lead_id

Revision ID: 2026_05_24_booking_lead_id
Revises: 2026_05_23_booking_reminder
Create Date: 2026-05-24 10:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "2026_05_24_booking_lead_id"
down_revision: Union[str, Sequence[str], None] = "2026_05_23_booking_reminder"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "bookings",
        sa.Column(
            "lead_id",
            sa.UUID(),
            sa.ForeignKey("leads.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_bookings_lead_id", "bookings", ["lead_id"])


def downgrade() -> None:
    op.drop_index("ix_bookings_lead_id", table_name="bookings")
    op.drop_column("bookings", "lead_id")
