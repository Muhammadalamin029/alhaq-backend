"""add_bed_bath_sqft_to_property

Revision ID: 6a14408677c4
Revises: 4b06b54684d0
Create Date: 2026-08-12 11:32:54.229237

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '6a14408677c4'
down_revision = '4b06b54684d0'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('properties', sa.Column('bedrooms', sa.Integer(), nullable=True))
    op.add_column('properties', sa.Column('bathrooms', sa.Numeric(precision=3, scale=1), nullable=True))
    op.add_column('properties', sa.Column('square_feet', sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column('properties', 'square_feet')
    op.drop_column('properties', 'bathrooms')
    op.drop_column('properties', 'bedrooms')
