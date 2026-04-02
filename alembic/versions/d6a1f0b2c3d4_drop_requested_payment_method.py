"""drop requested payment method

Revision ID: d6a1f0b2c3d4
Revises: c3b9a7d4e6f0
Create Date: 2026-03-30 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "d6a1f0b2c3d4"
down_revision = "c3b9a7d4e6f0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    migration_context = op.get_context()
    if migration_context.as_sql:
        op.drop_column("payments", "requested_payment_method")
        return

    inspector = sa.inspect(op.get_bind())
    existing_columns = {column["name"] for column in inspector.get_columns("payments")}
    if "requested_payment_method" in existing_columns:
        op.drop_column("payments", "requested_payment_method")


def downgrade() -> None:
    op.add_column(
        "payments",
        sa.Column("requested_payment_method", sa.String(length=50), nullable=True),
    )
