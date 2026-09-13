"""add_financing_notification_types

Revision ID: 0c5cf35fd55a
Revises: 1f831f5de5a2
Create Date: 2026-09-13 00:00:01.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0c5cf35fd55a'
down_revision = '1f831f5de5a2'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Postgres ENUM types cannot be easily updated within a transaction.
    # Use op.execute to add values one by one.

    op.execute("ALTER TYPE notification_type ADD VALUE 'financing_application_submitted'")
    op.execute("ALTER TYPE notification_type ADD VALUE 'financing_application_approved'")
    op.execute("ALTER TYPE notification_type ADD VALUE 'financing_application_rejected'")
    op.execute("ALTER TYPE notification_type ADD VALUE 'financing_application_revoked'")


def downgrade() -> None:
    # Downgrading ENUM values in Postgres is non-trivial and often not recommended
    # as it requires dropping the type or recreating it.
    pass
