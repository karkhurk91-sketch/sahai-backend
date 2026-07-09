"""Add facebook_pages and scheduled fields

Revision ID: 37b5237b9ac9_phase2
Revises: 37b5237b9ac9
Create Date: 2026-06-14 18:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = '37b5237b9ac9_phase2'
down_revision = '37b5237b9ac9'
branch_labels = None
depends_on = None

def upgrade():
    # Create facebook_pages table
    op.create_table(
        'facebook_pages',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, default=sa.text('gen_random_uuid()')),
        sa.Column('organization_id', UUID(as_uuid=True), nullable=False),
        sa.Column('page_id', sa.String(255), nullable=False),
        sa.Column('page_name', sa.String(255), nullable=False),
        sa.Column('page_access_token', sa.Text, nullable=False),
        sa.Column('page_category', sa.String(100), nullable=True),
        sa.Column('follower_count', sa.Integer, nullable=True),
        sa.Column('is_active', sa.Boolean, default=False),
        sa.Column('last_synced_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), onupdate=sa.func.now()),
    )
    op.create_index('ix_facebook_pages_org_page', 'facebook_pages', ['organization_id', 'page_id'], unique=True)

    # Extend facebook_posts
    op.add_column('facebook_posts', sa.Column('scheduled_for', sa.DateTime(timezone=True), nullable=True))
    op.add_column('facebook_posts', sa.Column('is_scheduled', sa.Boolean, default=False))
    op.create_index('ix_facebook_posts_scheduled', 'facebook_posts', ['scheduled_for'])

def downgrade():
    op.drop_index('ix_facebook_posts_scheduled', table_name='facebook_posts')
    op.drop_column('facebook_posts', 'is_scheduled')
    op.drop_column('facebook_posts', 'scheduled_for')
    op.drop_index('ix_facebook_pages_org_page', table_name='facebook_pages')
    op.drop_table('facebook_pages')
