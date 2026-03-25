"""Add buildings_count to re_session_requests

Revision ID: 67f87d811ff6
Revises: c951e1a491ff
Create Date: 2026-03-24 22:57:27.660716

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '67f87d811ff6'
down_revision = 'c951e1a491ff'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('re_session_requests', sa.Column('buildings_count', sa.Integer(), nullable=True, server_default='1'))


def downgrade() -> None:
    op.drop_column('re_session_requests', 'buildings_count')
