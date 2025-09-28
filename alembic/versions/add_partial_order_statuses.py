"""Add partial order statuses to order_status enum

Revision ID: add_partial_order_statuses
Revises: increase_order_amount_precision
Create Date: 2025-09-28 10:17:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'add_partial_order_statuses'
down_revision = 'increase_order_amount_precision'
branch_labels = None
depends_on = None


def upgrade():
    # Add new values to the order_status enum
    # PostgreSQL requires using ALTER TYPE to add enum values
    op.execute("ALTER TYPE order_status ADD VALUE 'partially_shipped'")
    op.execute("ALTER TYPE order_status ADD VALUE 'partially_delivered'")
    op.execute("ALTER TYPE order_status ADD VALUE 'partially_cancelled'")


def downgrade():
    # Note: PostgreSQL doesn't support removing enum values directly
    # This would require recreating the enum type and updating all references
    # For safety, we'll leave a comment about manual intervention needed
    
    # WARNING: Cannot automatically remove enum values in PostgreSQL
    # Manual intervention required:
    # 1. Ensure no orders use the partial statuses
    # 2. Create new enum without partial values
    # 3. Update column to use new enum
    # 4. Drop old enum
    
    pass  # No automatic downgrade possible
