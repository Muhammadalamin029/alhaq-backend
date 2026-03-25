"""update re_session_status to add processing

Revision ID: f3b4c5d6e7f8
Revises: f2b3c4d5e6f7
Create Date: 2026-03-23 20:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'f3b4c5d6e7f8'
down_revision = 'f2b3c4d5e6f7'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add 'processing' to re_session_status enum
    op.execute("ALTER TYPE re_session_status ADD VALUE 'processing'")


def downgrade() -> None:
    # Cannot easily remove enum values in PG
    pass
