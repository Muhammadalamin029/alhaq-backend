"""update_order_items_status_check_constraint

Revision ID: fab7b2c68a8c
Revises: 355198702506
Create Date: 2025-10-03 16:52:17.611773

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'fab7b2c68a8c'
down_revision = '355198702506'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Drop the existing check constraint
    op.drop_constraint('order_items_status_check', 'order_items', type_='check')
    
    # Create a new check constraint that includes 'paid'
    op.create_check_constraint(
        'order_items_status_check',
        'order_items',
        "status IN ('pending', 'processing', 'paid', 'shipped', 'delivered', 'cancelled')"
    )


def downgrade() -> None:
    # Drop the updated check constraint
    op.drop_constraint('order_items_status_check', 'order_items', type_='check')
    
    # Recreate the original check constraint without 'paid'
    op.create_check_constraint(
        'order_items_status_check',
        'order_items',
        "status IN ('pending', 'processing', 'shipped', 'delivered', 'cancelled')"
    )
