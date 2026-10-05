"""add product listing indexes

Revision ID: b2c3d4e5f6a7
Revises: s2t0r3e5t6o7
Create Date: 2026-10-05 00:00:00.000000

Speeds up storefront listing (status/category/price/created_at + name search)
which backs the new short-TTL Redis cache-aside in routers/products.py.
"""
from alembic import op


revision = 'b2c3d4e5f6a7'
down_revision = 's2t0r3e5t6o7'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_products_status_category_created "
        "ON products (status, category_id, created_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_products_price ON products (price)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_products_category ON products (category_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_products_status ON products (status)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_products_name_trgm "
        "ON products USING gin (name gin_trgm_ops)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_products_name_trgm")
    op.execute("DROP INDEX IF EXISTS ix_products_status")
    op.execute("DROP INDEX IF EXISTS ix_products_category")
    op.execute("DROP INDEX IF EXISTS ix_products_price")
    op.execute("DROP INDEX IF EXISTS ix_products_status_category_created")
