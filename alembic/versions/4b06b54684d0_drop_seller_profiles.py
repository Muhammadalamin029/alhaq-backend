"""drop_seller_profiles

Phase B of the multi-vendor -> single-vendor conversion. Phase A
(1d938efa9253) introduced `store_profiles` and reassigned/narrowed the
`users.role` enum, but deliberately left `seller_profiles` (and the
inventory/asset tables FK'ing into it) alone since the Python code still
queried it directly. That code is now gone, so this migration finishes the
job:

  1. For each of `products`, `payments`, `cars`, `properties`,
     `general_inspections`, `general_agreements`: drop the `seller_id` FK
     into `seller_profiles`, reassign every existing row's `seller_id` to
     the single `store_profiles` row (fetched at migration time -- Phase A
     guarantees exactly one exists), then recreate the FK pointing at
     `store_profiles.id`. The column stays named `seller_id` (unchanged)
     to match the already-updated ORM models/queries -- only what it
     references changes.
  2. Drops `seller_profiles` (index + table).
  3. Drops the `seller_type` and `seller_kyc_status` enums, which existed
     solely for `seller_profiles`.

Data-fidelity note (mirrors the accepted limitation in
a1b2c3d4e5f6_remove_phone_dealer.py and 1d938efa9253_single_vendor_conversion.py):
step 1's reassignment overwrites per-row seller attribution with the single
store -- which seller originally owned which product/car/property/payment/
inspection/agreement is not recoverable. Downgrade restores the
`seller_profiles` table, its enums, and the FK structure so the schema
shape round-trips, but it cannot repopulate the original multi-seller rows.
To keep the restored FK constraints valid against the (unavoidably
single-store) data left by step 1, downgrade seeds `seller_profiles` with
one synthetic row copied from `store_profiles` (same id, so every
`seller_id` FK still resolves) and does NOT restore
`seller_profiles.id`'s original FK to `users.id` -- that constraint
required a real per-seller user account, and there's no user to attach the
synthetic row to without fabricating a fake one, which would be a worse
data-integrity violation than dropping the constraint. This is called out
explicitly since it's the one place downgrade doesn't fully mirror the
original schema.

Revision ID: 4b06b54684d0
Revises: 1d938efa9253
Create Date: 2026-08-09 16:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = '4b06b54684d0'
down_revision = '1d938efa9253'
branch_labels = None
depends_on = None


# Tables whose seller_id FK moves from seller_profiles.id to store_profiles.id
_SELLER_ID_TABLES = [
    "products",
    "payments",
    "cars",
    "properties",
    "general_inspections",
    "general_agreements",
]


def upgrade() -> None:
    bind = op.get_bind()

    # ------------------------------------------------------------------
    # 0. Fetch the single store_profiles row (seeded by Phase A)
    # ------------------------------------------------------------------
    store_id = bind.execute(sa.text("SELECT id FROM store_profiles LIMIT 1")).scalar()
    if store_id is None:
        raise RuntimeError(
            "No store_profiles row found -- expected exactly one, seeded by "
            "1d938efa9253_single_vendor_conversion."
        )

    # ------------------------------------------------------------------
    # 1. Repoint seller_id on every inventory/asset table from
    #    seller_profiles.id to store_profiles.id
    # ------------------------------------------------------------------
    for table in _SELLER_ID_TABLES:
        op.drop_constraint(f"{table}_seller_id_fkey", table, type_="foreignkey")
        bind.execute(
            sa.text(f"UPDATE {table} SET seller_id = :store_id"),
            {"store_id": store_id},
        )
        op.create_foreign_key(
            f"{table}_seller_id_fkey",
            table,
            "store_profiles",
            ["seller_id"],
            ["id"],
        )

    # ------------------------------------------------------------------
    # 2. Drop seller_profiles (index + table)
    # ------------------------------------------------------------------
    op.drop_index("ix_seller_profiles_id", table_name="seller_profiles")
    op.drop_table("seller_profiles")

    # ------------------------------------------------------------------
    # 3. Drop enums that existed solely for seller_profiles
    # ------------------------------------------------------------------
    op.execute("DROP TYPE IF EXISTS seller_type")
    op.execute("DROP TYPE IF EXISTS seller_kyc_status")


def downgrade() -> None:
    bind = op.get_bind()

    # ------------------------------------------------------------------
    # 3. Recreate enums
    # ------------------------------------------------------------------
    op.execute("CREATE TYPE seller_type AS ENUM ('retailer', 'car_dealer', 'real_agent')")
    op.execute("CREATE TYPE seller_kyc_status AS ENUM ('pending', 'approved', 'rejected')")

    # ------------------------------------------------------------------
    # 2. Recreate seller_profiles (structure only -- see data-fidelity
    #    note above for why the id -> users.id FK is intentionally not
    #    restored).
    # ------------------------------------------------------------------
    op.create_table(
        "seller_profiles",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("business_name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("logo_url", sa.Text(), nullable=True),
        sa.Column("contact_email", sa.String(length=255), nullable=True),
        sa.Column("contact_phone", sa.String(length=50), nullable=True),
        sa.Column("website_url", sa.Text(), nullable=True),
        sa.Column(
            "seller_type",
            postgresql.ENUM("retailer", "car_dealer", "real_agent", name="seller_type", create_type=False),
            nullable=True,
        ),
        sa.Column(
            "kyc_status",
            postgresql.ENUM("pending", "approved", "rejected", name="seller_kyc_status", create_type=False),
            nullable=True,
        ),
        sa.Column("approval_date", sa.Date(), nullable=True),
        sa.Column("total_products", sa.Integer(), nullable=True),
        sa.Column("total_orders", sa.Integer(), nullable=True),
        sa.Column("total_revenue", sa.DECIMAL(precision=12, scale=2), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=True),
        sa.Column("updated_at", sa.TIMESTAMP(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=True),
        sa.Column("available_balance", sa.DECIMAL(precision=12, scale=2), nullable=True),
        sa.Column("pending_balance", sa.DECIMAL(precision=12, scale=2), nullable=True),
        sa.Column("total_paid", sa.DECIMAL(precision=12, scale=2), nullable=True),
        sa.Column("payout_account_number", sa.String(length=20), nullable=True),
        sa.Column("payout_bank_code", sa.String(length=10), nullable=True),
        sa.Column("payout_bank_name", sa.String(length=100), nullable=True),
        sa.Column("payout_recipient_code", sa.String(length=100), nullable=True),
        sa.Column("default_grace_period_days", sa.Integer(), nullable=True, server_default="3"),
        sa.PrimaryKeyConstraint("id", name="seller_profiles_pkey"),
    )
    op.create_index("ix_seller_profiles_id", "seller_profiles", ["id"], unique=False)

    # Seed one synthetic seller_profiles row so the FK constraints below
    # (re-added against existing seller_id data left pointing at the store)
    # validate. See data-fidelity note in the module docstring.
    bind.execute(
        sa.text(
            """
            INSERT INTO seller_profiles (id, business_name, description, contact_email, contact_phone, website_url)
            SELECT id, business_name, description, contact_email, contact_phone, website_url
            FROM store_profiles
            LIMIT 1
            """
        )
    )

    # ------------------------------------------------------------------
    # 1. Repoint seller_id back to seller_profiles.id
    # ------------------------------------------------------------------
    for table in _SELLER_ID_TABLES:
        op.drop_constraint(f"{table}_seller_id_fkey", table, type_="foreignkey")
        op.create_foreign_key(
            f"{table}_seller_id_fkey",
            table,
            "seller_profiles",
            ["seller_id"],
            ["id"],
        )
