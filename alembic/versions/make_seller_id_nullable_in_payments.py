"""Make seller_id nullable in payments table

Revision ID: make_seller_id_nullable_in_payments
Revises: add_partial_order_statuses
Create Date: 2025-01-27 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'make_seller_id_nullable_in_payments'
down_revision = 'add_partial_order_statuses'
branch_labels = None
depends_on = None


def upgrade():
    # Make seller_id column nullable in payments table
    op.alter_column('payments', 'seller_id',
                    existing_type=sa.UUID(),
                    nullable=True)


def downgrade():
    # Make seller_id column not nullable in payments table
    # Note: This will fail if there are any NULL values in seller_id
    op.alter_column('payments', 'seller_id',
                    existing_type=sa.UUID(),
                    nullable=False)
