"""add deletion grace-period fields to users

Revision ID: d5e6f7a8b9c1
Revises: d4e5f6a7b8c9
Create Date: 2026-10-05

Play-compliant account deletion: DELETE /auth/me schedules purge in 30 days.
Anonymized escrow/financial ledgers retained up to 7 years (AML/tax/deed tracing).
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd5e6f7a8b9c1'
down_revision = 'd4e5f6a7b8c9'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('users', sa.Column('deletion_requested_at', sa.TIMESTAMP(), nullable=True))
    op.add_column('users', sa.Column('deleted_at', sa.TIMESTAMP(), nullable=True))
    op.create_index('ix_users_deleted_at', 'users', ['deleted_at'])


def downgrade() -> None:
    op.drop_index('ix_users_deleted_at', table_name='users')
    op.drop_column('users', 'deleted_at')
    op.drop_column('users', 'deletion_requested_at')
