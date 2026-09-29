"""rename_store_to_lel_store

Revision ID: s2t0r3e5t6o7
Revises: x1t2e3r4n5a6
Create Date: 2026-09-29 00:00:00.000000

The site brands as "LEL Store" everywhere (frontend BRAND, backend
PROJECT_NAME/FROM_NAME, system-settings default) except the
store_profiles row seeded as "LEL Marketplace", which is what receipts
(and admin surfaces) display. Rename existing rows; the model default
is updated alongside.
"""
from alembic import op


# revision identifiers, used by Alembic.
revision = 's2t0r3e5t6o7'
down_revision = 'x1t2e3r4n5a6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "UPDATE store_profiles SET business_name = 'LEL Store' "
        "WHERE business_name = 'LEL Marketplace'"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE store_profiles SET business_name = 'LEL Marketplace' "
        "WHERE business_name = 'LEL Store'"
    )
