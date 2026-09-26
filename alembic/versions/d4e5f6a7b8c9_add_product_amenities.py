"""add_product_amenities

Revision ID: d4e5f6a7b8c9
Revises: b8c9d0e1f2a3
Create Date: 2026-09-26 00:00:00.000000

Adds structured amenities (list of feature strings) to products,
mirroring properties.amenities (b7c8d9e0f1a2).

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd4e5f6a7b8c9'
down_revision = 'b8c9d0e1f2a3'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('products', sa.Column('amenities', sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column('products', 'amenities')
