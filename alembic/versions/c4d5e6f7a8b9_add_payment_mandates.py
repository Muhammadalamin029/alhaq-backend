"""add_payment_mandates

Revision ID: c4d5e6f7a8b9
Revises: b7ea6ef89055
Create Date: 2026-08-30 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c4d5e6f7a8b9'
down_revision = 'b7ea6ef89055'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'payment_mandates',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('agreement_id', sa.UUID(), nullable=False),
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column('provider', sa.String(length=50), nullable=False, server_default='paystack'),
        sa.Column('status', sa.Enum('pending_authorization', 'active', 'revoked', 'failed', name='mandate_status'), nullable=True, server_default='pending_authorization'),
        sa.Column('email', sa.String(length=255), nullable=False),
        sa.Column('reference', sa.String(length=100), nullable=True),
        sa.Column('authorization_code', sa.String(length=100), nullable=True),
        sa.Column('bank_name', sa.String(length=100), nullable=True),
        sa.Column('account_number_last4', sa.String(length=10), nullable=True),
        sa.Column('failed_attempts', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('authorized_at', sa.TIMESTAMP(), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=True),
        sa.Column('updated_at', sa.TIMESTAMP(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=True),
        sa.ForeignKeyConstraint(['agreement_id'], ['general_agreements.id'], ),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('agreement_id'),
    )
    op.create_index(op.f('ix_payment_mandates_id'), 'payment_mandates', ['id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_payment_mandates_id'), table_name='payment_mandates')
    op.drop_table('payment_mandates')
    sa.Enum(name='mandate_status').drop(op.get_bind(), checkfirst=True)
