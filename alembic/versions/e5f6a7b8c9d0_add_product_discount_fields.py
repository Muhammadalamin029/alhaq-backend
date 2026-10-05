"""add product discount fields

Revision ID: e5f6a7b8c9d0
Revises: b2c3d4e5f6a7
Create Date: 2026-10-05 00:00:00.000000

Adds sale support to products: discount percent + optional window.
Base price is never mutated; effective price derives at read/checkout time.
"""
from alembic import op
import sqlalchemy as sa


revision = 'e5f6a7b8c9d0'
down_revision = 'b2c3d4e5f6a7'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('products', sa.Column('discount_percent', sa.Numeric(5, 2), nullable=True))
    op.add_column('products', sa.Column('discount_starts_at', sa.TIMESTAMP(), nullable=True))
    op.add_column('products', sa.Column('discount_ends_at', sa.TIMESTAMP(), nullable=True))
    op.execute("CREATE INDEX IF NOT EXISTS ix_products_discount_ends ON products (discount_ends_at)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_products_discount_ends")
    op.drop_column('products', 'discount_ends_at')
    op.drop_column('products', 'discount_starts_at')
    op.drop_column('products', 'discount_percent')
