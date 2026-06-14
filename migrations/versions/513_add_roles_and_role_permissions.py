"""add roles and role_permissions tables

Revision ID: 513
Revises: 004
Create Date: 2026-06-11 12:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = '513'
down_revision = '004'
branch_labels = None
depends_on = None

def upgrade():
    # Create roles table with default UUID generation
    op.create_table('roles',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('name', sa.String(50), nullable=False, unique=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), onupdate=sa.text('now()')),
    )
    # Create role_permissions table
    op.create_table('role_permissions',
        sa.Column('role_id', UUID(as_uuid=True), sa.ForeignKey('roles.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('permission_id', UUID(as_uuid=True), sa.ForeignKey('permissions.id', ondelete='CASCADE'), primary_key=True),
    )
    # Insert default roles – IDs will be auto-generated
    op.execute("INSERT INTO roles (name) VALUES ('super_admin'), ('org_admin'), ('partner'), ('agent'), ('viewer')")

def downgrade():
    op.drop_table('role_permissions')
    op.drop_table('roles')