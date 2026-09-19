"""add_promo_banner_settings

Revision ID: b1d2e3f4a5c6
Revises: e4f5a6b7c8d9
Create Date: 2026-09-19 09:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "b1d2e3f4a5c6"
down_revision = "e4f5a6b7c8d9"
branch_labels = None
depends_on = None


COLUMNS = [
    ("promo_banner_enabled", sa.Boolean(), sa.false()),
    ("promo_banner_tag", sa.String(length=50), "Sale"),
    ("promo_banner_headline", sa.String(length=255), "Huge Savings"),
    ("promo_banner_discount_prefix", sa.String(length=100), "Up to"),
    ("promo_banner_discount_value", sa.String(length=50), "59%"),
    ("promo_banner_discount_suffix", sa.String(length=50), "OFF"),
    ("promo_banner_cta_text", sa.String(length=100), "Shop Now"),
    ("promo_banner_cta_link", sa.String(length=255), "/products"),
]


def upgrade() -> None:
    migration_context = op.get_context()
    if migration_context.as_sql:
        for name, column_type, default in COLUMNS:
            op.add_column(
                "system_settings",
                sa.Column(
                    name,
                    column_type,
                    nullable=name != "promo_banner_enabled",
                    server_default=default,
                ),
            )
        return

    inspector = sa.inspect(op.get_bind())
    existing_columns = {column["name"] for column in inspector.get_columns("system_settings")}
    for name, column_type, default in COLUMNS:
        if name not in existing_columns:
            op.add_column(
                "system_settings",
                sa.Column(
                    name,
                    column_type,
                    nullable=name != "promo_banner_enabled",
                    server_default=default,
                ),
            )


def downgrade() -> None:
    for name, _column_type, _default in reversed(COLUMNS):
        op.drop_column("system_settings", name)
