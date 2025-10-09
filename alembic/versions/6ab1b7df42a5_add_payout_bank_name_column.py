"""add_payout_bank_name_column

Revision ID: 6ab1b7df42a5
Revises: ceeafac384c6
Create Date: 2025-10-09 21:53:30.551129

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '6ab1b7df42a5'
down_revision = 'ceeafac384c6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add payout_bank_name column to seller_profiles table
    op.add_column('seller_profiles', 
                  sa.Column('payout_bank_name', sa.String(length=100), nullable=True))


def downgrade() -> None:
    # Remove payout_bank_name column from seller_profiles table
    op.drop_column('seller_profiles', 'payout_bank_name')
