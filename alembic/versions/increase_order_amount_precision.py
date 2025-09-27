"""Increase order total_amount precision

Revision ID: increase_order_amount_precision
Revises: 
Create Date: 2025-09-27 17:01:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'increase_order_amount_precision'
down_revision = None  # Update this with the latest revision ID
branch_labels = None
depends_on = None


def upgrade():
    # Increase precision from Numeric(10,2) to Numeric(15,2) for all price/amount fields
    # This allows values up to 9,999,999,999,999.99 (almost 10 trillion)
    
    # Update orders.total_amount
    op.alter_column('orders', 'total_amount',
                    existing_type=sa.Numeric(precision=10, scale=2),
                    type_=sa.Numeric(precision=15, scale=2),
                    existing_nullable=False)
    
    # Update order_items.price
    op.alter_column('order_items', 'price',
                    existing_type=sa.Numeric(precision=10, scale=2),
                    type_=sa.Numeric(precision=15, scale=2),
                    existing_nullable=False)
    
    # Update products.price
    op.alter_column('products', 'price',
                    existing_type=sa.Numeric(precision=10, scale=2),
                    type_=sa.Numeric(precision=15, scale=2),
                    existing_nullable=False)


def downgrade():
    # Revert back to original precision (be careful with data loss)
    op.alter_column('orders', 'total_amount',
                    existing_type=sa.Numeric(precision=15, scale=2),
                    type_=sa.Numeric(precision=10, scale=2),
                    existing_nullable=False)
    
    op.alter_column('order_items', 'price',
                    existing_type=sa.Numeric(precision=15, scale=2),
                    type_=sa.Numeric(precision=10, scale=2),
                    existing_nullable=False)
    
    op.alter_column('products', 'price',
                    existing_type=sa.Numeric(precision=15, scale=2),
                    type_=sa.Numeric(precision=10, scale=2),
                    existing_nullable=False)
