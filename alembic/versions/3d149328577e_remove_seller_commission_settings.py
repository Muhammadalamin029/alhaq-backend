"""remove_seller_commission_settings

Revision ID: 3d149328577e
Revises: ac430d82987d
Create Date: 2026-09-11 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '3d149328577e'
down_revision = 'ac430d82987d'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # These seller commission/payout settings were never actually consumed by
    # any payout or fee logic - removing the unused admin controls and columns.
    op.drop_column('system_settings', 'minimum_payout_amount')
    op.drop_column('system_settings', 'commission_rate_percent')


def downgrade() -> None:
    op.add_column('system_settings', sa.Column('commission_rate_percent', sa.Numeric(5, 2), nullable=False, server_default='5.00'))
    op.add_column('system_settings', sa.Column('minimum_payout_amount', sa.Numeric(15, 2), nullable=False, server_default='10000'))
