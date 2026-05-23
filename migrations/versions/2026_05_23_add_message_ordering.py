"""add_message_ordering_fields

Revision ID: 2026_05_23_msg_order
Revises: 04931066a40e
Create Date: 2026-05-23 00:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from datetime import datetime, timezone

# revision identifiers, used by Alembic.
revision: str = '2026_05_23_msg_order'
down_revision: Union[str, Sequence[str], None] = '04931066a40e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add message ordering fields and constraints."""
    
    # 1. Add new columns (nullable initially for backfill)
    op.add_column('messages', sa.Column('whatsapp_timestamp', sa.Integer(), nullable=True))
    op.add_column('messages', sa.Column('sort_timestamp', sa.DateTime(timezone=True), nullable=True))
    
    # 2. Add unique constraint to whatsapp_message_id
    op.create_unique_constraint(
        'uq_messages_whatsapp_id',
        'messages',
        ['whatsapp_message_id']
    )
    
    # 3. Create indexes for sorting queries
    op.create_index(
        'ix_messages_sort_timestamp',
        'messages',
        ['sort_timestamp']
    )
    op.create_index(
        'ix_messages_conversation_sort',
        'messages',
        ['conversation_id', 'sort_timestamp']
    )
    
    # 4. Backfill existing messages
    # For existing messages, use created_at as the source of truth
    # Convert created_at to Unix timestamp and then back to sort_timestamp
    connection = op.get_bind()
    
    # Backfill sort_timestamp from created_at
    update_query = """
    UPDATE messages 
    SET 
        sort_timestamp = COALESCE(created_at, NOW()),
        whatsapp_timestamp = EXTRACT(EPOCH FROM COALESCE(created_at, NOW()))::bigint
    WHERE sort_timestamp IS NULL;
    """
    connection.execute(sa.text(update_query))
    
    # 5. Set NOT NULL constraints after backfill
    op.alter_column('messages', 'sort_timestamp', nullable=False)
    op.alter_column('messages', 'whatsapp_timestamp', nullable=False)


def downgrade() -> None:
    """Remove message ordering fields."""
    
    # Drop indexes
    op.drop_index('ix_messages_conversation_sort', table_name='messages')
    op.drop_index('ix_messages_sort_timestamp', table_name='messages')
    
    # Drop unique constraint
    op.drop_constraint('uq_messages_whatsapp_id', 'messages', type_='unique')
    
    # Drop columns
    op.drop_column('messages', 'sort_timestamp')
    op.drop_column('messages', 'whatsapp_timestamp')
