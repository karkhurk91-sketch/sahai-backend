"""add_facebook_posts_table

Revision ID: 37b5237b9ac9
Revises: 513
Create Date: 2026-06-14 17:26:25.398880

"""
from typing import Sequence, Union

# migrations/versions/xxxx_add_facebook_posts_table.py
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = '37b5237b9ac9'
down_revision = '513'  # replace with your last revision
branch_labels = None
depends_on = None

def upgrade():
    op.create_table(
        'facebook_posts',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, default=sa.text('gen_random_uuid()')),
        sa.Column('organization_id', UUID(as_uuid=True), nullable=False),
        sa.Column('page_id', sa.String(255), nullable=False),
        sa.Column('meta_post_id', sa.String(255), nullable=True),
        sa.Column('title', sa.Text, nullable=True),
        sa.Column('content', sa.Text, nullable=False),
        sa.Column('hashtags', sa.Text, nullable=True),
        sa.Column('media_url', sa.Text, nullable=True),
        sa.Column('media_type', sa.String(20), nullable=True),
        sa.Column('status', sa.String(20), nullable=False, server_default='draft'),
        sa.Column('error_message', sa.Text, nullable=True),
        sa.Column('boost_campaign_id', sa.String(255), nullable=True),
        sa.Column('published_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), onupdate=sa.func.now()),
    )
    op.create_index('ix_facebook_posts_org_status', 'facebook_posts', ['organization_id', 'status'])
    op.create_index('ix_facebook_posts_org_created', 'facebook_posts', ['organization_id', 'created_at'])

def downgrade():
    op.drop_index('ix_facebook_posts_org_created', table_name='facebook_posts')
    op.drop_index('ix_facebook_posts_org_status', table_name='facebook_posts')
    op.drop_table('facebook_posts')