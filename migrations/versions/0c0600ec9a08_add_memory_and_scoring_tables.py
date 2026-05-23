"""add_memory_and_scoring_tables

Revision ID: 0c0600ec9a08
Revises: 04931066a40e
Create Date: 2026-05-22 12:30:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers
revision = '0c0600ec9a08'
down_revision = '04931066a40e'
branch_labels = None
depends_on = None


def upgrade():
    # Create conversation_memories table (idempotent)
    op.execute("""
        CREATE TABLE IF NOT EXISTS conversation_memories (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            conversation_id UUID REFERENCES conversations(id) ON DELETE CASCADE,
            facts JSONB,
            last_summary TEXT,
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT now()
        )
    """)
    
    # Add index on leads.lead_score if not exists
    op.execute("CREATE INDEX IF NOT EXISTS idx_leads_lead_score ON leads(lead_score)")


def downgrade():
    op.execute("DROP TABLE IF EXISTS conversation_memories")
    # Optionally drop the index, but only if you created it; we keep it for safety
    # op.execute("DROP INDEX IF EXISTS idx_leads_lead_score")