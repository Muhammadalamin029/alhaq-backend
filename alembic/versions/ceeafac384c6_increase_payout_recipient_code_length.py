"""increase_payout_recipient_code_length

Revision ID: ceeafac384c6
Revises: 924c0bc6f92f
Create Date: 2025-10-09 21:40:20.239325

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'ceeafac384c6'
down_revision = '924c0bc6f92f'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Increase payout_recipient_code field length from 50 to 100 characters
    op.alter_column('seller_profiles', 'payout_recipient_code',
                    existing_type=sa.String(length=50),
                    type_=sa.String(length=100),
                    existing_nullable=True)


def downgrade() -> None:
    # Revert payout_recipient_code field length back to 50 characters
    op.alter_column('seller_profiles', 'payout_recipient_code',
                    existing_type=sa.String(length=100),
                    type_=sa.String(length=50),
                    existing_nullable=True)
