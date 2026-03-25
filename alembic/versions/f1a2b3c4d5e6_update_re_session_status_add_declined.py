"""update re_session_status enum to add declined

Revision ID: f1a2b3c4d5e6
Revises: ee45bcc501bb
Create Date: 2026-03-23 19:17:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'f1a2b3c4d5e6'
down_revision = 'ee45bcc501bb'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # PostgreSQL requires renaming old type, creating new one, then updating the column
    op.execute("ALTER TYPE re_session_status ADD VALUE IF NOT EXISTS 'declined'")
    op.execute("ALTER TYPE re_session_status ADD VALUE IF NOT EXISTS 'inspecting'")


def downgrade() -> None:
    # PostgreSQL does not support removing enum values directly.
    # Downgrade is a no-op — removing enum values requires full type recreation.
    pass
