"""add product description trigram index

Revision ID: f8a9b0c1d2e3
Revises: e5f6a7b8c9d0
Create Date: 2026-10-06 00:00:00.000000

Backs fuzzy product search (name + description) in core/products.py.
pg_trgm itself was enabled by b2c3d4e5f6a7; this adds the missing
description-side GIN index.
"""
from alembic import op


revision = 'f8a9b0c1d2e3'
down_revision = 'e5f6a7b8c9d0'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_products_description_trgm "
        "ON products USING gin (lower(description) gin_trgm_ops)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_products_description_trgm")
