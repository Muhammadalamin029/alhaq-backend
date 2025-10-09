"""Add payment_url and payment_reference columns to orders and related fields in payments

Revision ID: 61b4f56b51cb
Revises: 7f1c5a2584f8
Create Date: 2025-10-06 13:46:07.955672
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '61b4f56b51cb'
down_revision = '7f1c5a2584f8'
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.add_column('orders', sa.Column('payment_url', sa.Text(), nullable=True))
    op.add_column('orders', sa.Column('payment_reference', sa.String(length=100), nullable=True))
    op.add_column('orders', sa.Column('payment_initialized_at', sa.TIMESTAMP(), nullable=True))

    op.add_column('payments', sa.Column('authorization_url', sa.Text(), nullable=True))
    op.add_column('payments', sa.Column('access_code', sa.String(length=100), nullable=True))
    op.add_column('payments', sa.Column('reference', sa.String(length=100), nullable=True))
    op.alter_column('payments', 'seller_id', nullable=True)

def downgrade() -> None:
    op.alter_column('payments', 'seller_id', nullable=False)
    op.drop_column('payments', 'reference')
    op.drop_column('payments', 'access_code')
    op.drop_column('payments', 'authorization_url')
    op.drop_column('orders', 'payment_initialized_at')
    op.drop_column('orders', 'payment_reference')
    op.drop_column('orders', 'payment_url')
