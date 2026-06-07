"""add metadata column to payments table

Revision ID: a2b3c4d5e6f7
Revises: f3b4c5d6e7f8
Create Date: 2026-06-07 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSON


# revision identifiers, used by Alembic.
revision = 'a2b3c4d5e6f7'
down_revision = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('payments', sa.Column('transaction_metadata', JSON, nullable=True))


def downgrade() -> None:
    op.drop_column('payments', 'transaction_metadata')
