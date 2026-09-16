"""add_order_pickup_address

Revision ID: e4f5a6b7c8d9
Revises: d1e2f3a4b5c6
Create Date: 2026-09-16 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e4f5a6b7c8d9'
down_revision = 'd1e2f3a4b5c6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('orders', sa.Column('pickup_address', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('orders', 'pickup_address')
