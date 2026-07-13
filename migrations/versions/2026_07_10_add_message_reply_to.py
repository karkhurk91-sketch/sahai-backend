"""Add reply_to_id foreign key to messages table

Revision ID: 2026_07_10_add_message_reply_to
Revises: 
Create Date: 2026-07-10 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = '2026_07_10_add_message_reply_to'
down_revision = None
branch_labels = None
depends_on = None

def upgrade():
    op.add_column('messages', sa.Column('reply_to_id', UUID(as_uuid=True), nullable=True))
    op.create_foreign_key('fk_messages_reply_to_id', 'messages', 'messages', ['reply_to_id'], ['id'], ondelete='SET NULL')
    op.create_index('ix_messages_reply_to_id', 'messages', ['reply_to_id'])

def downgrade():
    op.drop_index('ix_messages_reply_to_id', table_name='messages')
    op.drop_constraint('fk_messages_reply_to_id', 'messages', type_='foreignkey')
    op.drop_column('messages', 'reply_to_id')
