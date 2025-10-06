"""Add seller payout system

Revision ID: ced7a101d720
Revises: make_seller_id_nullable_in_payments
Create Date: 2025-10-01 16:07:34.842915

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'ced7a101d720'
down_revision = 'add_partial_order_statuses'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Check if payout_status enum exists, create if not
    connection = op.get_bind()
    result = connection.execute(sa.text("""
        SELECT 1 FROM pg_type WHERE typname = 'payout_status'
    """))
    if not result.fetchone():
        op.execute("CREATE TYPE payout_status AS ENUM ('pending', 'processing', 'completed', 'failed', 'cancelled')")
    
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
    
    # Create seller_payouts table
    op.create_table('seller_payouts',
        sa.Column('id', postgresql.UUID(), nullable=False),
        sa.Column('seller_id', postgresql.UUID(), nullable=False),
        sa.Column('amount', sa.DECIMAL(precision=12, scale=2), nullable=False),
        sa.Column('platform_fee', sa.DECIMAL(precision=12, scale=2), nullable=True, default=0),
        sa.Column('net_amount', sa.DECIMAL(precision=12, scale=2), nullable=False),
        sa.Column('status', sa.Enum('pending', 'processing', 'completed', 'failed', 'cancelled', name='payout_status'), nullable=True, default='pending'),
        sa.Column('transfer_reference', sa.String(length=100), nullable=True),
        sa.Column('paystack_transfer_id', sa.String(length=100), nullable=True),
        sa.Column('recipient_code', sa.String(length=50), nullable=True),
        sa.Column('account_number', sa.String(length=20), nullable=True),
        sa.Column('bank_code', sa.String(length=10), nullable=True),
        sa.Column('bank_name', sa.String(length=100), nullable=True),
        sa.Column('processed_at', sa.TIMESTAMP(), nullable=True),
        sa.Column('failure_reason', sa.Text(), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=True),
        sa.Column('updated_at', sa.TIMESTAMP(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=True),
        sa.ForeignKeyConstraint(['seller_id'], ['seller_profiles.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('transfer_reference')
    )
    
    op.create_index(op.f('ix_seller_payouts_id'), 'seller_payouts', ['id'], unique=False)
    op.create_index(op.f('ix_seller_payouts_seller_id'), 'seller_payouts', ['seller_id'], unique=False)


def downgrade() -> None:
    # Drop seller_payouts table
    op.drop_index(op.f('ix_seller_payouts_seller_id'), table_name='seller_payouts')
    op.drop_index(op.f('ix_seller_payouts_id'), table_name='seller_payouts')
    op.drop_table('seller_payouts')
    
    # Drop payout-related columns from seller_profiles table
    op.drop_column('seller_profiles', 'payout_recipient_code')
    op.drop_column('seller_profiles', 'payout_bank_code')
    op.drop_column('seller_profiles', 'payout_account_number')
    op.drop_column('seller_profiles', 'total_paid')
    op.drop_column('seller_profiles', 'pending_balance')
    op.drop_column('seller_profiles', 'available_balance')
    
    # Drop the payout_status enum
    op.execute("DROP TYPE IF EXISTS payout_status")
