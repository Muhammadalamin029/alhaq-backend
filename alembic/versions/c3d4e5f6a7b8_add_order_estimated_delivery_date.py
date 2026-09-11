"""add_order_estimated_delivery_date

Revision ID: c3d4e5f6a7b8
Revises: b7c8d9e0f1a2
Create Date: 2026-09-13 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c3d4e5f6a7b8'
down_revision = 'b7c8d9e0f1a2'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('orders', sa.Column('estimated_delivery_date', sa.TIMESTAMP(), nullable=True))


def downgrade() -> None:
    op.drop_column('orders', 'estimated_delivery_date')
