"""add_conversation_state_machine_fields

Revision ID: 2026_05_25_state_machine
Revises: 2026_05_24_booking_lead_id
Create Date: 2026-05-25 08:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "2026_05_25_state_machine"
down_revision: Union[str, Sequence[str], None] = "2026_05_24_booking_lead_id"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "conversations",
        sa.Column(
            "conversation_stage",
            sa.String(50),
            server_default="greeting",
            nullable=False,
        ),
    )
    op.add_column(
        "conversations",
        sa.Column(
            "completed_fields",
            sa.JSON(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(
        "conversations",
        sa.Column(
            "booking_status",
            sa.String(50),
            nullable=True,
        ),
    )
    op.add_column(
        "conversations",
        sa.Column(
            "recommendation_shown",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )
    op.add_column(
        "conversations",
        sa.Column(
            "last_intent",
            sa.String(100),
            nullable=True,
        ),
    )
    op.create_index("ix_conversations_stage", "conversations", ["conversation_stage"])
    op.create_index("ix_conversations_booking_status", "conversations", ["booking_status"])


def downgrade() -> None:
    op.drop_index("ix_conversations_booking_status", table_name="conversations")
    op.drop_index("ix_conversations_stage", table_name="conversations")
    op.drop_column("conversations", "last_intent")
    op.drop_column("conversations", "recommendation_shown")
    op.drop_column("conversations", "booking_status")
    op.drop_column("conversations", "completed_fields")
    op.drop_column("conversations", "conversation_stage")
