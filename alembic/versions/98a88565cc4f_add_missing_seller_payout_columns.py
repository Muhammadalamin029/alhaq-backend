"""Add missing seller payout columns

Revision ID: 98a88565cc4f
Revises: ced7a101d720
Create Date: 2025-10-01 16:16:35.425384

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '98a88565cc4f'
down_revision = 'ced7a101d720'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add payout-related columns to seller_profiles table
    op.add_column('seller_profiles', sa.Column('available_balance', sa.DECIMAL(precision=12, scale=2), nullable=True, default=0))
    op.add_column('seller_profiles', sa.Column('pending_balance', sa.DECIMAL(precision=12, scale=2), nullable=True, default=0))
    op.add_column('seller_profiles', sa.Column('total_paid', sa.DECIMAL(precision=12, scale=2), nullable=True, default=0))
    op.add_column('seller_profiles', sa.Column('payout_account_number', sa.String(length=20), nullable=True))
    op.add_column('seller_profiles', sa.Column('payout_bank_code', sa.String(length=10), nullable=True))
    op.add_column('seller_profiles', sa.Column('payout_recipient_code', sa.String(length=50), nullable=True))
    
    # Set default values for existing records
    op.execute("UPDATE seller_profiles SET available_balance = 0 WHERE available_balance IS NULL")
    op.execute("UPDATE seller_profiles SET pending_balance = 0 WHERE pending_balance IS NULL")
    op.execute("UPDATE seller_profiles SET total_paid = 0 WHERE total_paid IS NULL")


def downgrade() -> None:
    # Drop payout-related columns from seller_profiles table
    op.drop_column('seller_profiles', 'payout_recipient_code')
    op.drop_column('seller_profiles', 'payout_bank_code')
    op.drop_column('seller_profiles', 'payout_account_number')
    op.drop_column('seller_profiles', 'total_paid')
    op.drop_column('seller_profiles', 'pending_balance')
    op.drop_column('seller_profiles', 'available_balance')
