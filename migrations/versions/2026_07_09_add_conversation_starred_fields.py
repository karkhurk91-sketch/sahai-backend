from alembic import op
import sqlalchemy as sa

revision = '2026_07_09_add_conversation_starred_fields'
down_revision = '004_add_message_mode_and_status_updated_at'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('conversations', sa.Column('is_starred', sa.Boolean(), nullable=True, server_default=sa.false()))
    op.add_column('conversations', sa.Column('starred_at', sa.DateTime(timezone=True), nullable=True))
    op.create_index(op.f('ix_conversations_is_starred'), 'conversations', ['is_starred'], unique=False)
    op.create_index(op.f('ix_conversations_unread_count'), 'conversations', ['unread_count'], unique=False)


def downgrade():
    op.drop_index(op.f('ix_conversations_unread_count'), table_name='conversations')
    op.drop_index(op.f('ix_conversations_is_starred'), table_name='conversations')
    op.drop_column('conversations', 'starred_at')
    op.drop_column('conversations', 'is_starred')
