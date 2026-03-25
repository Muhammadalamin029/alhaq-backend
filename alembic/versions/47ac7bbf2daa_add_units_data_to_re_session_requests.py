"""add units_data to re_session_requests

Revision ID: 47ac7bbf2daa
Revises: 52f172ea16c8
Create Date: 2026-03-24 23:39:38.364458

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '47ac7bbf2daa'
down_revision = '52f172ea16c8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('re_session_requests', sa.Column('units_data', sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column('re_session_requests', 'units_data')
