"""add_property_amenities_and_location

Revision ID: b7c8d9e0f1a2
Revises: 3d149328577e
Create Date: 2026-09-12 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b7c8d9e0f1a2'
down_revision = '3d149328577e'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('properties', sa.Column('amenities', sa.JSON(), nullable=True))
    op.add_column('properties', sa.Column('latitude', sa.Numeric(9, 6), nullable=True))
    op.add_column('properties', sa.Column('longitude', sa.Numeric(9, 6), nullable=True))


def downgrade() -> None:
    op.drop_column('properties', 'longitude')
    op.drop_column('properties', 'latitude')
    op.drop_column('properties', 'amenities')
