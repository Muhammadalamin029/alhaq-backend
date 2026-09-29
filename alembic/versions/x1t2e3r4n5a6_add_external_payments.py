"""add_external_payments

Revision ID: x1t2e3r4n5a6
Revises: e9f1a2b3c4d5
Create Date: 2026-09-29 00:00:00.000000

Standalone ledger for admin-recorded offline sales (cash / bank_transfer /
POS). New tables only — `payments` is untouched.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'x1t2e3r4n5a6'
down_revision = 'e9f1a2b3c4d5'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'external_payments',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('receipt_number', sa.String(length=50), nullable=False),
        sa.Column('payer_name', sa.String(length=255), nullable=False),
        sa.Column('payer_email', sa.String(length=255), nullable=False),
        sa.Column('payer_phone', sa.String(length=50), nullable=True),
        sa.Column('buyer_id', sa.UUID(), nullable=True),
        sa.Column('amount', sa.Numeric(15, 2), nullable=False),
        sa.Column('channel', sa.Enum('cash', 'bank_transfer', 'pos',
                                     name='external_payment_channel'),
                  nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False,
                  server_default='completed'),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('paid_at', sa.TIMESTAMP(),
                  server_default=sa.text('CURRENT_TIMESTAMP'), nullable=True),
        sa.Column('recorded_by', sa.UUID(), nullable=False),
        sa.Column('pdf_url', sa.Text(), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(),
                  server_default=sa.text('CURRENT_TIMESTAMP'), nullable=True),
        sa.Column('updated_at', sa.TIMESTAMP(),
                  server_default=sa.text('CURRENT_TIMESTAMP'), nullable=True),
        sa.ForeignKeyConstraint(['buyer_id'], ['profiles.id'], ),
        sa.ForeignKeyConstraint(['recorded_by'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_external_payments_id'),
                    'external_payments', ['id'], unique=False)
    op.create_index(op.f('ix_external_payments_payer_email'),
                    'external_payments', ['payer_email'], unique=False)
    op.create_index(op.f('ix_external_payments_receipt_number'),
                    'external_payments', ['receipt_number'], unique=True)

    op.create_table(
        'external_payment_items',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('external_payment_id', sa.UUID(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('quantity', sa.Integer(), nullable=False),
        sa.Column('unit_price', sa.Numeric(15, 2), nullable=False),
        sa.Column('created_at', sa.TIMESTAMP(),
                  server_default=sa.text('CURRENT_TIMESTAMP'), nullable=True),
        sa.ForeignKeyConstraint(['external_payment_id'],
                                ['external_payments.id'],
                                ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_external_payment_items_external_payment_id'),
                    'external_payment_items', ['external_payment_id'],
                    unique=False)
    op.create_index(op.f('ix_external_payment_items_id'),
                    'external_payment_items', ['id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_external_payment_items_id'),
                  table_name='external_payment_items')
    op.drop_index(op.f('ix_external_payment_items_external_payment_id'),
                  table_name='external_payment_items')
    op.drop_table('external_payment_items')
    op.drop_index(op.f('ix_external_payments_receipt_number'),
                  table_name='external_payments')
    op.drop_index(op.f('ix_external_payments_payer_email'),
                  table_name='external_payments')
    op.drop_index(op.f('ix_external_payments_id'),
                  table_name='external_payments')
    op.drop_table('external_payments')
    op.execute('DROP TYPE IF EXISTS external_payment_channel')
