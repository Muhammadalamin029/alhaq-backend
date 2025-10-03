"""Add payment URL fields and paid status

Revision ID: add_payment_url_fields
Revises: ced7a101d720
Create Date: 2025-10-03 14:45:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'add_payment_url_fields'
down_revision = 'ced7a101d720'
branch_labels = None
depends_on = None


def upgrade():
    # Add 'paid' to order_status enum
    op.execute("ALTER TYPE order_status ADD VALUE 'paid'")
    
    # Add payment URL fields to orders table
    op.add_column('orders', sa.Column('payment_url', sa.Text(), nullable=True))
    op.add_column('orders', sa.Column('payment_reference', sa.String(length=100), nullable=True))
    op.add_column('orders', sa.Column('payment_initialized_at', sa.TIMESTAMP(), nullable=True))
    
    # Add payment URL fields to payments table
    op.add_column('payments', sa.Column('authorization_url', sa.Text(), nullable=True))
    op.add_column('payments', sa.Column('access_code', sa.String(length=100), nullable=True))
    op.add_column('payments', sa.Column('reference', sa.String(length=100), nullable=True))


def downgrade():
    # Remove payment URL fields from payments table
    op.drop_column('payments', 'reference')
    op.drop_column('payments', 'access_code')
    op.drop_column('payments', 'authorization_url')
    
    # Remove payment URL fields from orders table
    op.drop_column('orders', 'payment_initialized_at')
    op.drop_column('orders', 'payment_reference')
    op.drop_column('orders', 'payment_url')
    
    # Note: Cannot remove enum values in PostgreSQL easily
    # The 'paid' value will remain in the enum but won't be used
