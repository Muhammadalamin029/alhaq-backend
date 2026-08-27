"""fix_null_kyc_status

Revision ID: b7ea6ef89055
Revises: 6a14408677c4
Create Date: 2026-08-23 16:40:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b7ea6ef89055'
down_revision = '6a14408677c4'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Backfill rows inserted outside the ORM (which relied on a Python-side
    # default) and left kyc_status NULL, then enforce a DB-level default
    # and NOT NULL so this can't happen again.
    op.execute("UPDATE profiles SET kyc_status = 'pending' WHERE kyc_status IS NULL")
    op.alter_column(
        'profiles',
        'kyc_status',
        existing_type=sa.Enum('pending', 'approved', 'rejected', name='kyc_status'),
        nullable=False,
        server_default='pending',
    )


def downgrade() -> None:
    op.alter_column(
        'profiles',
        'kyc_status',
        existing_type=sa.Enum('pending', 'approved', 'rejected', name='kyc_status'),
        nullable=True,
        server_default=None,
    )
