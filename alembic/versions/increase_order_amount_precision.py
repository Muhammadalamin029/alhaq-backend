"""Increase order total_amount precision

Revision ID: increase_order_amount_precision
Revises: 
Create Date: 2025-09-28 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'increase_order_amount_precision'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # Increase precision of total_amount column in orders table
    op.alter_column('orders', 'total_amount',
                    existing_type=sa.DECIMAL(precision=10, scale=2),
                    type_=sa.DECIMAL(precision=12, scale=2),
                    existing_nullable=False)


def downgrade():
    # Decrease precision back to original
    op.alter_column('orders', 'total_amount',
                    existing_type=sa.DECIMAL(precision=12, scale=2),
                    type_=sa.DECIMAL(precision=10, scale=2),
                    existing_nullable=False)
