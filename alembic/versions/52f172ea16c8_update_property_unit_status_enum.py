"""update property_unit_status enum

Revision ID: 52f172ea16c8
Revises: 68157138703e
Create Date: 2026-03-24 23:38:10.401540

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '52f172ea16c8'
down_revision = '68157138703e'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Postgres specific ALTER TYPE to add new values to Enum
    op.execute("COMMIT")
    op.execute("ALTER TYPE property_unit_status ADD VALUE 'pending_inspection'")
    op.execute("ALTER TYPE property_unit_status ADD VALUE 'property_inspected'")
    op.execute("ALTER TYPE property_unit_status ADD VALUE 'rented'")
    op.execute("ALTER TYPE property_unit_status ADD VALUE 'under_financing'")


def downgrade() -> None:
    pass
