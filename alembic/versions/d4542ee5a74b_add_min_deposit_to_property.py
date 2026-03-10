"""add_min_deposit_to_property

Revision ID: d4542ee5a74b
Revises: 751a8ca89e25
Create Date: 2026-03-10 01:31:06.638026

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd4542ee5a74b'
down_revision = '751a8ca89e25'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('properties', sa.Column('min_deposit_percentage', sa.Numeric(precision=5, scale=2), server_default='10', nullable=True))


def downgrade() -> None:
    op.drop_column('properties', 'min_deposit_percentage')
