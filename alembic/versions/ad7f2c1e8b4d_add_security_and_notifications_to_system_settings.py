"""add_security_and_notifications_to_system_settings

Revision ID: ad7f2c1e8b4d
Revises: 9c4d7e6f1a2b
Create Date: 2026-03-30 16:28:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "ad7f2c1e8b4d"
down_revision = "9c4d7e6f1a2b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    migration_context = op.get_context()
    if migration_context.as_sql:
        op.add_column(
            "system_settings",
            sa.Column("require_email_verification", sa.Boolean(), nullable=False, server_default=sa.true()),
        )
        op.add_column(
            "system_settings",
            sa.Column("require_seller_kyc", sa.Boolean(), nullable=False, server_default=sa.true()),
        )
        op.add_column(
            "system_settings",
            sa.Column("access_token_lifetime_minutes", sa.Integer(), nullable=False, server_default="30"),
        )
        op.add_column(
            "system_settings",
            sa.Column("max_login_attempts", sa.Integer(), nullable=False, server_default="5"),
        )
        op.add_column(
            "system_settings",
            sa.Column("lockout_duration_minutes", sa.Integer(), nullable=False, server_default="15"),
        )
        op.add_column(
            "system_settings",
            sa.Column("new_user_notifications", sa.Boolean(), nullable=False, server_default=sa.true()),
        )
        op.add_column(
            "system_settings",
            sa.Column("new_seller_notifications", sa.Boolean(), nullable=False, server_default=sa.true()),
        )
        op.add_column(
            "system_settings",
            sa.Column("dispute_notifications", sa.Boolean(), nullable=False, server_default=sa.true()),
        )
        op.add_column(
            "system_settings",
            sa.Column("system_alerts", sa.Boolean(), nullable=False, server_default=sa.true()),
        )
        op.add_column(
            "system_settings",
            sa.Column("weekly_reports", sa.Boolean(), nullable=False, server_default=sa.true()),
        )
        return

    inspector = sa.inspect(op.get_bind())
    existing_columns = {column["name"] for column in inspector.get_columns("system_settings")}
    columns_to_add = [
        ("require_email_verification", sa.Boolean(), sa.true()),
        ("require_seller_kyc", sa.Boolean(), sa.true()),
        ("access_token_lifetime_minutes", sa.Integer(), "30"),
        ("max_login_attempts", sa.Integer(), "5"),
        ("lockout_duration_minutes", sa.Integer(), "15"),
        ("new_user_notifications", sa.Boolean(), sa.true()),
        ("new_seller_notifications", sa.Boolean(), sa.true()),
        ("dispute_notifications", sa.Boolean(), sa.true()),
        ("system_alerts", sa.Boolean(), sa.true()),
        ("weekly_reports", sa.Boolean(), sa.true()),
    ]
    for name, column_type, default in columns_to_add:
        if name not in existing_columns:
            op.add_column(
                "system_settings",
                sa.Column(name, column_type, nullable=False, server_default=default),
            )


def downgrade() -> None:
    op.drop_column("system_settings", "weekly_reports")
    op.drop_column("system_settings", "system_alerts")
    op.drop_column("system_settings", "dispute_notifications")
    op.drop_column("system_settings", "new_seller_notifications")
    op.drop_column("system_settings", "new_user_notifications")
    op.drop_column("system_settings", "lockout_duration_minutes")
    op.drop_column("system_settings", "max_login_attempts")
    op.drop_column("system_settings", "access_token_lifetime_minutes")
    op.drop_column("system_settings", "require_seller_kyc")
    op.drop_column("system_settings", "require_email_verification")
