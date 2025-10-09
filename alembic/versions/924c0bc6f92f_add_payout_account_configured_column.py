"""add_payout_account_configured_column

Revision ID: 924c0bc6f92f
Revises: 7e5fac565111
Create Date: 2025-10-09 17:48:27.701785

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '924c0bc6f92f'
down_revision = '7e5fac565111'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add payout_account_configured column to seller_profiles table
    op.add_column('seller_profiles', sa.Column('payout_account_configured', sa.Boolean(), nullable=True, default=False))
    
    # Update existing records to set payout_account_configured based on existing data
    op.execute("""
        UPDATE seller_profiles 
        SET payout_account_configured = (
            payout_account_number IS NOT NULL 
            AND payout_bank_code IS NOT NULL 
            AND payout_recipient_code IS NOT NULL
        )
    """)
    
    # Set NOT NULL constraint after updating existing records
    op.alter_column('seller_profiles', 'payout_account_configured', nullable=False)


def downgrade() -> None:
    # Remove payout_account_configured column
    op.drop_column('seller_profiles', 'payout_account_configured')
