"""add_payment_receipt_number

Revision ID: a9b8c7d6e5f4
Revises: b1d2e3f4a5c6
Create Date: 2026-09-23 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "a9b8c7d6e5f4"
down_revision = "b1d2e3f4a5c6"
branch_labels = None
depends_on = None


BACKFILL = sa.text(
    """
    UPDATE payments
    SET receipt_number = 'RCPT-' || to_char(created_at, 'YYYYMMDD') || '-'
                         || upper(substr(replace(id::text, '-', ''), 1, 8))
    WHERE receipt_number IS NULL
    """
)

DUPLICATE_CHECK = sa.text(
    """
    SELECT receipt_number, COUNT(*) AS copies
    FROM payments
    WHERE receipt_number IS NOT NULL
    GROUP BY receipt_number
    HAVING COUNT(*) > 1
    """
)


def upgrade() -> None:
    op.add_column(
        "payments",
        sa.Column("receipt_number", sa.String(length=50), nullable=True),
    )

    op.execute(BACKFILL)

    duplicates = op.get_bind().execute(DUPLICATE_CHECK).fetchall()
    if duplicates:
        raise RuntimeError(
            "Cannot create unique index on payments.receipt_number: "
            f"{len(duplicates)} duplicated value(s): "
            + ", ".join(str(row[0]) for row in duplicates[:10])
        )

    op.create_index(
        "ix_payments_receipt_number",
        "payments",
        ["receipt_number"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_payments_receipt_number", table_name="payments")
    op.drop_column("payments", "receipt_number")
