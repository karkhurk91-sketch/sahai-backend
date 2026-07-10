from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = '2026_07_09_add_customer_profile_and_conversation_starred_columns'
down_revision = '2026_07_09_add_conversation_starred_fields'
branch_labels = None
depends_on = None


def _column_exists(bind, table_name: str, column_name: str) -> bool:
    inspector = inspect(bind)
    return any(column['name'] == column_name for column in inspector.get_columns(table_name))


def _index_exists(bind, table_name: str, index_name: str) -> bool:
    inspector = inspect(bind)
    return any(index['name'] == index_name for index in inspector.get_indexes(table_name))


def upgrade():
    bind = op.get_bind()

    if not _column_exists(bind, 'customers', 'profile_picture'):
        op.add_column('customers', sa.Column('profile_picture', sa.String(500), nullable=True))

    if not _column_exists(bind, 'conversations', 'is_starred'):
        op.add_column('conversations', sa.Column('is_starred', sa.Boolean(), nullable=True, server_default=sa.false()))

    if not _column_exists(bind, 'conversations', 'starred_at'):
        op.add_column('conversations', sa.Column('starred_at', sa.DateTime(timezone=True), nullable=True))

    if not _index_exists(bind, 'conversations', 'ix_conversations_is_starred'):
        op.create_index(op.f('ix_conversations_is_starred'), 'conversations', ['is_starred'], unique=False)

    if not _index_exists(bind, 'conversations', 'ix_conversations_unread_count'):
        op.create_index(op.f('ix_conversations_unread_count'), 'conversations', ['unread_count'], unique=False)


def downgrade():
    bind = op.get_bind()
    if _index_exists(bind, 'conversations', 'ix_conversations_unread_count'):
        op.drop_index(op.f('ix_conversations_unread_count'), table_name='conversations')
    if _index_exists(bind, 'conversations', 'ix_conversations_is_starred'):
        op.drop_index(op.f('ix_conversations_is_starred'), table_name='conversations')
    if _column_exists(bind, 'conversations', 'starred_at'):
        op.drop_column('conversations', 'starred_at')
    if _column_exists(bind, 'conversations', 'is_starred'):
        op.drop_column('conversations', 'is_starred')
    if _column_exists(bind, 'customers', 'profile_picture'):
        op.drop_column('customers', 'profile_picture')
