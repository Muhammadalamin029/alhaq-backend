"""replace_processing_fee_with_inspection_policy

Revision ID: c3b9a7d4e6f0
Revises: ad7f2c1e8b4d
Create Date: 2026-03-30 18:10:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "c3b9a7d4e6f0"
down_revision = "ad7f2c1e8b4d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    migration_context = op.get_context()
    if migration_context.as_sql:
        op.drop_column("system_settings", "processing_fee_percent")
        op.add_column(
            "system_settings",
            sa.Column("minimum_inspection_notice_hours", sa.Integer(), nullable=False, server_default="24"),
        )
        op.add_column(
            "system_settings",
            sa.Column("inspection_cancellation_cutoff_hours", sa.Integer(), nullable=False, server_default="12"),
        )
        op.add_column(
            "system_settings",
            sa.Column("missed_inspection_expiry_hours", sa.Integer(), nullable=False, server_default="24"),
        )
        return

    inspector = sa.inspect(op.get_bind())
    existing_columns = {column["name"] for column in inspector.get_columns("system_settings")}
    if "processing_fee_percent" in existing_columns:
        op.drop_column("system_settings", "processing_fee_percent")
    if "minimum_inspection_notice_hours" not in existing_columns:
        op.add_column(
            "system_settings",
            sa.Column("minimum_inspection_notice_hours", sa.Integer(), nullable=False, server_default="24"),
        )
    if "inspection_cancellation_cutoff_hours" not in existing_columns:
        op.add_column(
            "system_settings",
            sa.Column("inspection_cancellation_cutoff_hours", sa.Integer(), nullable=False, server_default="12"),
        )
    if "missed_inspection_expiry_hours" not in existing_columns:
        op.add_column(
            "system_settings",
            sa.Column("missed_inspection_expiry_hours", sa.Integer(), nullable=False, server_default="24"),
        )


def downgrade() -> None:
    op.drop_column("system_settings", "missed_inspection_expiry_hours")
    op.drop_column("system_settings", "inspection_cancellation_cutoff_hours")
    op.drop_column("system_settings", "minimum_inspection_notice_hours")
    op.add_column(
        "system_settings",
        sa.Column("processing_fee_percent", sa.Numeric(5, 2), nullable=False, server_default="2.50"),
    )
