"""Add phone field to customer profiles

Revision ID: ce480483f3de
Revises: 61b4f56b51cb
Create Date: 2025-10-09 11:15:02.060919

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'ce480483f3de'
down_revision = '61b4f56b51cb'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add phone field to profiles table
    op.add_column('profiles', sa.Column('phone', sa.String(length=50), nullable=True))


def downgrade() -> None:
    # Remove phone field from profiles table
    op.drop_column('profiles', 'phone')
