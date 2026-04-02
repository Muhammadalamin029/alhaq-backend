"""create_system_settings_table

Revision ID: 9c4d7e6f1a2b
Revises: 85bfbcbd9295
Create Date: 2026-03-30 16:20:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "9c4d7e6f1a2b"
down_revision = "85bfbcbd9295"
branch_labels = None
depends_on = None


def upgrade() -> None:
    migration_context = op.get_context()
    if migration_context.as_sql:
        op.create_table(
            "system_settings",
            sa.Column("id", sa.UUID(), nullable=False, server_default=sa.text("gen_random_uuid()")),
            sa.Column("scope", sa.String(length=50), nullable=False, server_default="default"),
            sa.Column("site_name", sa.String(length=255), nullable=False, server_default="Alhaq"),
            sa.Column("site_description", sa.Text(), nullable=True),
            sa.Column("contact_email", sa.String(length=255), nullable=True),
            sa.Column("support_email", sa.String(length=255), nullable=True),
            sa.Column("currency", sa.String(length=10), nullable=False, server_default="NGN"),
            sa.Column("language", sa.String(length=10), nullable=False, server_default="en"),
            sa.Column("timezone", sa.String(length=100), nullable=False, server_default="Africa/Lagos"),
            sa.Column("commission_rate_percent", sa.Numeric(5, 2), nullable=False, server_default="5.00"),
            sa.Column("processing_fee_percent", sa.Numeric(5, 2), nullable=False, server_default="2.50"),
            sa.Column("minimum_payout_amount", sa.Numeric(15, 2), nullable=False, server_default="10000.00"),
            sa.Column("payout_schedule", sa.String(length=20), nullable=False, server_default="weekly"),
            sa.Column("updated_by_user_id", sa.UUID(), nullable=True),
            sa.Column("created_at", sa.TIMESTAMP(), nullable=True, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("updated_at", sa.TIMESTAMP(), nullable=True, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.ForeignKeyConstraint(["updated_by_user_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("scope"),
        )
        op.create_index(op.f("ix_system_settings_id"), "system_settings", ["id"], unique=False)
        return

    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "system_settings" not in inspector.get_table_names():
        op.create_table(
            "system_settings",
            sa.Column("id", sa.UUID(), nullable=False, server_default=sa.text("gen_random_uuid()")),
            sa.Column("scope", sa.String(length=50), nullable=False, server_default="default"),
            sa.Column("site_name", sa.String(length=255), nullable=False, server_default="Alhaq"),
            sa.Column("site_description", sa.Text(), nullable=True),
            sa.Column("contact_email", sa.String(length=255), nullable=True),
            sa.Column("support_email", sa.String(length=255), nullable=True),
            sa.Column("currency", sa.String(length=10), nullable=False, server_default="NGN"),
            sa.Column("language", sa.String(length=10), nullable=False, server_default="en"),
            sa.Column("timezone", sa.String(length=100), nullable=False, server_default="Africa/Lagos"),
            sa.Column("commission_rate_percent", sa.Numeric(5, 2), nullable=False, server_default="5.00"),
            sa.Column("processing_fee_percent", sa.Numeric(5, 2), nullable=False, server_default="2.50"),
            sa.Column("minimum_payout_amount", sa.Numeric(15, 2), nullable=False, server_default="10000.00"),
            sa.Column("payout_schedule", sa.String(length=20), nullable=False, server_default="weekly"),
            sa.Column("updated_by_user_id", sa.UUID(), nullable=True),
            sa.Column("created_at", sa.TIMESTAMP(), nullable=True, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("updated_at", sa.TIMESTAMP(), nullable=True, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.ForeignKeyConstraint(["updated_by_user_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("scope"),
        )

    existing_indexes = {idx["name"] for idx in inspector.get_indexes("system_settings")} if "system_settings" in inspector.get_table_names() else set()
    if op.f("ix_system_settings_id") not in existing_indexes:
        op.create_index(op.f("ix_system_settings_id"), "system_settings", ["id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_system_settings_id"), table_name="system_settings")
    op.drop_table("system_settings")
