"""add is_active to users

Revision ID: 4532f3ec3c7f
Revises: e8f9a0b1c2d3
Create Date: 2026-04-13 02:12:05.661454

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '4532f3ec3c7f'
down_revision = 'e8f9a0b1c2d3'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('users', sa.Column('is_active', sa.Boolean(), server_default='true', nullable=True))


def downgrade() -> None:
    op.drop_column('users', 'is_active')
