"""Add mode and status_updated_at to messages table

Revision ID: 004
Revises: 003_add_workflows   # CHANGE THIS to your previous migration ID
Create Date: 2026-06-10 12:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

revision = '004'
down_revision = '977a71d676b7'   # UPDATE THIS
branch_labels = None
depends_on = None

def upgrade():
    # Add mode column with server default 'ai'
    op.add_column('messages', sa.Column('mode', sa.String(20), nullable=False, server_default='ai'))
    
    # Add status_updated_at column (nullable)
    op.add_column('messages', sa.Column('status_updated_at', sa.DateTime(timezone=True), nullable=True))
    
    # Optional: Add indexes for faster filtering by mode
    op.create_index('ix_messages_mode', 'messages', ['mode'])

def downgrade():
    op.drop_index('ix_messages_mode', table_name='messages')
    op.drop_column('messages', 'status_updated_at')
    op.drop_column('messages', 'mode')