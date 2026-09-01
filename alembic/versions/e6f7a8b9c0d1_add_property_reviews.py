"""add_property_reviews

Revision ID: e6f7a8b9c0d1
Revises: d5e6f7a8b9c0
Create Date: 2026-09-01 00:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e6f7a8b9c0d1'
down_revision = 'd5e6f7a8b9c0'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('reviews', sa.Column('property_id', sa.UUID(), nullable=True))
    op.create_foreign_key('reviews_property_id_fkey', 'reviews', 'properties', ['property_id'], ['id'])


def downgrade() -> None:
    op.drop_constraint('reviews_property_id_fkey', 'reviews', type_='foreignkey')
    op.drop_column('reviews', 'property_id')
