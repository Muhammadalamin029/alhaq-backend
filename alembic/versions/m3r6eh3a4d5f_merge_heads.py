"""merge heads: receipt number + push tokens

Revision ID: m3r6eh3a4d5f
Revises: a9b8c7d6e5f4, p7u5h0t0k3n1
Create Date: 2026-09-25 00:00:00.000000

NOTE: older side branches (d6a1f0b2c3d4, e4f5a6b7c8d9) are intentionally NOT
merged here — several databases never recorded them, and a merge would crash
with KeyError on those environments. Their upgrades were made idempotent
(has_table/has_column guards) so `upgrade heads` converges everywhere.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'm3r6eh3a4d5f'
down_revision = ('a9b8c7d6e5f4', 'p7u5h0t0k3n1')
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
