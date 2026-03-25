"""Add acquired status to property status enum

Revision ID: c951e1a491ff
Revises: b7113dd13645
Create Date: 2026-03-24 22:53:04.082149

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c951e1a491ff'
down_revision = 'b7113dd13645'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # PostgreSQL requires ADD VALUE within its own transaction context
    op.execute("COMMIT")
    op.execute("ALTER TYPE property_status ADD VALUE IF NOT EXISTS 'acquired'")
    op.execute("ALTER TYPE re_session_status ADD VALUE IF NOT EXISTS 'acquired'")


def downgrade() -> None:
    pass
