"""flutterwave_provider_defaults

Revision ID: e9f1a2b3c4d5
Revises: d5e6f7a8b9c1, d6a1f0b2c3d4
Create Date: 2026-09-28 00:00:00.000000

Flutterwave cutover: new rows default to the flutterwave provider, and the
mandate authorization_code column is widened to hold Flutterwave card tokens
(flw-t1nf-...). Historical rows keep their stored 'paystack' values.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e9f1a2b3c4d5'
down_revision = ('d5e6f7a8b9c1', 'd6a1f0b2c3d4')
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        'payments',
        'payment_method',
        existing_type=sa.VARCHAR(length=50),
        server_default='flutterwave',
        existing_nullable=True,
    )
    op.alter_column(
        'payment_mandates',
        'provider',
        existing_type=sa.VARCHAR(length=50),
        server_default='flutterwave',
        existing_nullable=False,
    )
    op.alter_column(
        'payment_mandates',
        'authorization_code',
        existing_type=sa.VARCHAR(length=100),
        type_=sa.String(length=255),
        existing_nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        'payment_mandates',
        'authorization_code',
        existing_type=sa.VARCHAR(length=255),
        type_=sa.String(length=100),
        existing_nullable=True,
    )
    op.alter_column(
        'payment_mandates',
        'provider',
        existing_type=sa.VARCHAR(length=50),
        server_default='paystack',
        existing_nullable=False,
    )
    op.alter_column(
        'payments',
        'payment_method',
        existing_type=sa.VARCHAR(length=50),
        server_default='paystack',
        existing_nullable=True,
    )
