"""Add facebook_boosts table

Revision ID: add_facebook_boosts_c80b6d33
Revises: 37b5237b9ac9  # Change this to your last migration revision
Create Date: 2026-06-14T18:07:38.477207

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers, used by Alembic.
revision = 'add_facebook_boosts_c80b6d33'
down_revision = '37b5237b9ac9'  # Replace with your actual last revision
branch_labels = None
depends_on = None

def upgrade():
    op.create_table(
        'facebook_boosts',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, default=sa.text('gen_random_uuid()')),
        sa.Column('organization_id', UUID(as_uuid=True), nullable=False),
        sa.Column('post_id', UUID(as_uuid=True), nullable=False),
        sa.Column('meta_campaign_id', sa.String(255), nullable=True),
        sa.Column('meta_adset_id', sa.String(255), nullable=True),
        sa.Column('meta_ad_id', sa.String(255), nullable=True),
        sa.Column('daily_budget_cents', sa.Integer, nullable=False),
        sa.Column('duration_days', sa.Integer, nullable=False),
        sa.Column('targeting', sa.JSON, nullable=False),
        sa.Column('status', sa.String(20), nullable=False, server_default='active'),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('ended_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('error_message', sa.Text, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), onupdate=sa.func.now()),
    )
    op.create_index('ix_facebook_boosts_org', 'facebook_boosts', ['organization_id'])
    op.create_index('ix_facebook_boosts_post', 'facebook_boosts', ['post_id'])

def downgrade():
    op.drop_index('ix_facebook_boosts_post', table_name='facebook_boosts')
    op.drop_index('ix_facebook_boosts_org', table_name='facebook_boosts')
    op.drop_table('facebook_boosts')
