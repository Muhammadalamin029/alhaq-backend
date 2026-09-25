"""merge heads: receipt number + push tokens + older branches

Revision ID: m3r6eh3a4d5f
Revises: a9b8c7d6e5f4, p7u5h0t0k3n1, d6a1f0b2c3d4, e4f5a6b7c8d9
Create Date: 2026-09-25 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'm3r6eh3a4d5f'
down_revision = ('a9b8c7d6e5f4', 'p7u5h0t0k3n1', 'd6a1f0b2c3d4', 'e4f5a6b7c8d9')
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
