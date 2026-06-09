
"""create bot_configs table

Revision ID: xxxx
Revises: 5c7d47c6a512
Create Date: 2026-06-09 10:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '977a71d676b7'           # keep the generated ID
down_revision = '5c7d47c6a512'   # your previous head
branch_labels = None
depends_on = None

def upgrade():
    op.create_table('bot_configs',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('config', postgresql.JSONB(), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('created_by', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), onupdate=sa.func.now()),
    )
    op.create_foreign_key('fk_bot_configs_org', 'bot_configs', 'organizations', ['organization_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_bot_configs_user', 'bot_configs', 'users', ['created_by'], ['id'], ondelete='SET NULL')
    op.create_index('idx_bot_configs_org_active', 'bot_configs', ['organization_id', 'is_active'])

def downgrade():
    op.drop_index('idx_bot_configs_org_active', table_name='bot_configs')
    op.drop_constraint('fk_bot_configs_user', 'bot_configs', type_='foreignkey')
    op.drop_constraint('fk_bot_configs_org', 'bot_configs', type_='foreignkey')
    op.drop_table('bot_configs')