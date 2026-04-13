"""legal_documents: table + effective_date and structure_json

Revision ID: e8f9a0b1c2d3
Revises: d6a1f0b2c3d4
Create Date: 2026-04-11

Creates ``legal_documents`` if it does not exist (matches ``core.model.LegalDocument``).
If the table already exists (e.g. from ``Base.metadata.create_all``), adds only
``effective_date`` and ``structure_json`` when missing.
"""

from alembic import op
import sqlalchemy as sa


revision = "e8f9a0b1c2d3"
down_revision = "d6a1f0b2c3d4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    migration_context = op.get_context()
    if migration_context.as_sql:
        op.create_table(
            "legal_documents",
            sa.Column("slug", sa.String(length=32), nullable=False),
            sa.Column("body_html", sa.Text(), nullable=True),
            sa.Column("effective_date_label", sa.String(length=120), nullable=True),
            sa.Column("effective_date", sa.Date(), nullable=True),
            sa.Column("structure_json", sa.Text(), nullable=True),
            sa.Column(
                "updated_at",
                sa.TIMESTAMP(),
                server_default=sa.text("CURRENT_TIMESTAMP"),
                nullable=True,
            ),
            sa.PrimaryKeyConstraint("slug"),
        )
        return

    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "legal_documents" not in tables:
        op.create_table(
            "legal_documents",
            sa.Column("slug", sa.String(length=32), nullable=False),
            sa.Column("body_html", sa.Text(), nullable=True),
            sa.Column("effective_date_label", sa.String(length=120), nullable=True),
            sa.Column("effective_date", sa.Date(), nullable=True),
            sa.Column("structure_json", sa.Text(), nullable=True),
            sa.Column(
                "updated_at",
                sa.TIMESTAMP(),
                server_default=sa.text("CURRENT_TIMESTAMP"),
                nullable=True,
            ),
            sa.PrimaryKeyConstraint("slug"),
        )
        return

    columns = {c["name"] for c in inspector.get_columns("legal_documents")}
    if "effective_date" not in columns:
        op.add_column(
            "legal_documents",
            sa.Column("effective_date", sa.Date(), nullable=True),
        )
    if "structure_json" not in columns:
        op.add_column(
            "legal_documents",
            sa.Column("structure_json", sa.Text(), nullable=True),
        )


def downgrade() -> None:
    migration_context = op.get_context()
    if migration_context.as_sql:
        op.drop_column("legal_documents", "structure_json")
        op.drop_column("legal_documents", "effective_date")
        return

    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "legal_documents" not in inspector.get_table_names():
        return

    columns = {c["name"] for c in inspector.get_columns("legal_documents")}
    if "structure_json" in columns:
        op.drop_column("legal_documents", "structure_json")
    if "effective_date" in columns:
        op.drop_column("legal_documents", "effective_date")
