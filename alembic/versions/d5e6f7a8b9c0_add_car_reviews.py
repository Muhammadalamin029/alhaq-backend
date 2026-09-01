"""add_car_reviews

Revision ID: d5e6f7a8b9c0
Revises: c4d5e6f7a8b9
Create Date: 2026-09-01 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd5e6f7a8b9c0'
down_revision = 'c4d5e6f7a8b9'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('reviews', sa.Column('car_id', sa.UUID(), nullable=True))
    op.create_foreign_key('reviews_car_id_fkey', 'reviews', 'cars', ['car_id'], ['id'])
    op.alter_column('reviews', 'product_id', existing_type=sa.UUID(), nullable=True)


def downgrade() -> None:
    op.alter_column('reviews', 'product_id', existing_type=sa.UUID(), nullable=False)
    op.drop_constraint('reviews_car_id_fkey', 'reviews', type_='foreignkey')
    op.drop_column('reviews', 'car_id')
