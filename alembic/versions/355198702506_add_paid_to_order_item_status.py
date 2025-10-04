"""add_paid_to_order_item_status

Revision ID: 355198702506
Revises: 496fd00e7eed
Create Date: 2025-10-03 16:34:48.201053

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '355198702506'
down_revision = '496fd00e7eed'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add 'paid' to the order_item_status enum
    op.execute("ALTER TYPE order_item_status ADD VALUE 'paid' AFTER 'processing'")


def downgrade() -> None:
    # Note: PostgreSQL doesn't support removing enum values directly
    # This would require recreating the enum type and updating all references
    # For now, we'll leave the 'paid' value in the enum
    pass
