"""Add pinned messages table and max_pinned_messages column

Revision ID: 2d2ac2d0c348
Revises: 2026_07_10_add_message_reply_to
Create Date: 2026-07-14 18:03:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy import inspect

revision = '2d2ac2d0c348'
down_revision = '2026_07_10_add_message_reply_to'
branch_labels = None
depends_on = None

def table_exists(table_name):
    bind = op.get_bind()
    inspector = inspect(bind)
    return table_name in inspector.get_table_names()

def column_exists(table_name, column_name):
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = inspector.get_columns(table_name)
    return any(c['name'] == column_name for c in columns)

def upgrade():
    # Add max_pinned_messages column if it doesn't exist
    if not column_exists('organizations', 'max_pinned_messages'):
        op.add_column('organizations', sa.Column('max_pinned_messages', sa.Integer, server_default='3', nullable=False))

    # Create pinned_messages table only if it doesn't exist
    if not table_exists('pinned_messages'):
        op.create_table(
            'pinned_messages',
            sa.Column('id', UUID(as_uuid=True), primary_key=True, default=sa.text('gen_random_uuid()')),
            sa.Column('organization_id', UUID(as_uuid=True), nullable=False),
            sa.Column('conversation_id', UUID(as_uuid=True), nullable=False),
            sa.Column('message_id', UUID(as_uuid=True), nullable=False),
            sa.Column('pinned_by', UUID(as_uuid=True), nullable=False),
            sa.Column('pinned_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
            sa.Column('order_index', sa.Integer, server_default='0'),
            sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['conversation_id'], ['conversations.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['message_id'], ['messages.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['pinned_by'], ['users.id'], ondelete='SET NULL'),
            sa.UniqueConstraint('conversation_id', 'message_id', name='uq_pin_conv_msg'),
            sa.Index('idx_pinned_messages_conv', 'conversation_id'),
            sa.Index('idx_pinned_messages_org', 'organization_id'),
        )

def downgrade():
    if table_exists('pinned_messages'):
        op.drop_table('pinned_messages')
    if column_exists('organizations', 'max_pinned_messages'):
        op.drop_column('organizations', 'max_pinned_messages')