"""add_lead_ml_fields

Revision ID: 04931066a40e
Revises: a2f3594362bc
Create Date: 2026-05-22 11:46:52.472962

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '04931066a40e'
down_revision: Union[str, Sequence[str], None] = 'a2f3594362bc'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ==================================================
    # SAFE MIGRATION: Only ADD missing columns.
    # No drops, no alters of existing columns.
    # ==================================================

    # Add ML fields to leads table (if not exist, but Alembic will run once)
    op.add_column('leads', sa.Column('sentiment_score', sa.Float(), nullable=True))
    op.add_column('leads', sa.Column('intent_label', sa.String(length=50), nullable=True))
    
    # For embedding: use LargeBinary (PickleType maps to this in PostgreSQL)
    # If you prefer JSON, use sa.JSON() – but LargeBinary is fine.
    op.add_column('leads', sa.Column('embedding', sa.LargeBinary(), nullable=True))
    
    op.add_column('leads', sa.Column('last_scored_at', sa.DateTime(), nullable=True))
    op.add_column('leads', sa.Column('duplicate_checked', sa.Boolean(), nullable=True))
    op.add_column('leads', sa.Column('merged_into_id', postgresql.UUID(as_uuid=True), nullable=True))

    # Add foreign key for merged_into_id (self-reference)
    op.create_foreign_key(
        'fk_leads_merged_into',
        'leads', 'leads',
        ['merged_into_id'], ['id'],
        ondelete='SET NULL'
    )


def downgrade() -> None:
    # Remove the foreign key first, then columns
    op.drop_constraint('fk_leads_merged_into', 'leads', type_='foreignkey')
    op.drop_column('leads', 'merged_into_id')
    op.drop_column('leads', 'duplicate_checked')
    op.drop_column('leads', 'last_scored_at')
    op.drop_column('leads', 'embedding')
    op.drop_column('leads', 'intent_label')
    op.drop_column('leads', 'sentiment_score')