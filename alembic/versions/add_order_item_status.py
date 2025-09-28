"""Add status column to order_items table

Revision ID: add_order_item_status
Revises: add_partial_order_statuses
Create Date: 2025-01-28 16:57:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'add_order_item_status'
down_revision = 'add_partial_order_statuses'
branch_labels = None
depends_on = None


def upgrade():
    # Create the enum type for order item status if it doesn't exist
    op.execute("CREATE TYPE order_item_status AS ENUM ('pending', 'processing', 'shipped', 'delivered', 'cancelled')")
    
    # Add status column to order_items table
    op.add_column('order_items', sa.Column('status', 
                                          postgresql.ENUM('pending', 'processing', 'shipped', 'delivered', 'cancelled', 
                                                         name='order_item_status'), 
                                          nullable=False, 
                                          server_default='pending'))


def downgrade():
    # Remove the status column
    op.drop_column('order_items', 'status')
    
    # Drop the enum type
    op.execute("DROP TYPE order_item_status")
