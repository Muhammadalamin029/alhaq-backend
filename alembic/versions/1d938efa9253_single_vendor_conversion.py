"""single_vendor_conversion

Phase A of the multi-vendor -> single-vendor conversion. This migration:

  1. Creates the new `store_profiles` table (replaces the concept of a
     per-seller storefront with a single, site-wide store profile).
  2. Seeds exactly one `store_profiles` row.
  3. Backfills `profiles` rows for existing `role='admin'` users who already
     have a `seller_profiles` row (business_name -> name, description -> bio),
     since `Profile` is now the single place non-seller users get a
     name/bio from.
  4. Reassigns any existing `role='seller'` users to `role='customer'`
     (the seller role no longer exists).
  5. Narrows the `users.role` enum from `('customer', 'seller', 'admin')`
     down to `('customer', 'admin')`.
  6. Drops the `seller_payouts` table (payouts are Phase A, removed from
     the codebase already; no replacement in this phase).
  7. Removes the remaining DB objects for the real-estate session-request
     acquisition flow: the `acquisition_session_id` / `session_request_id`
     FK columns, the `re_session_requests` table, and the
     `re_session_status` enum.
  8. Drops `require_seller_kyc` / `new_seller_notifications` from
     `system_settings` and adds `default_grace_period_days`, seeded from
     an existing `seller_profiles.default_grace_period_days` value (or 7
     if none exists).

Note: `seller_profiles` itself (and its `seller_type` / `kyc_status`
enums) is intentionally NOT touched here -- Product/Payment/Car/Property/
GeneralInspection/GeneralAgreement still FK into it, and
`core/commission_service.py` / `routers/seller.py` still query it
directly. Dropping it is Phase B scope.

Data-fidelity note (mirrors the accepted limitation in
a1b2c3d4e5f6_remove_phone_dealer.py): steps 3 and 4 are reconciliation
steps, not lossless transforms. Downgrade cannot know which `customer`
users were originally `seller`s (step 4), nor cleanly distinguish the
`profiles` rows this migration backfilled from ones that legitimately
existed already (step 3). Downgrade widens the `role` enum back and
restores the dropped tables/columns, but does not attempt to reverse the
role reassignment or remove backfilled `profiles` rows.

Revision ID: 1d938efa9253
Revises: 38ba147c9b3b
Create Date: 2026-08-09 15:41:31.654562

"""
import uuid

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = '1d938efa9253'
down_revision = '38ba147c9b3b'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. Create store_profiles (single-vendor storefront)
    # ------------------------------------------------------------------
    op.create_table(
        'store_profiles',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('business_name', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('contact_email', sa.String(length=255), nullable=True),
        sa.Column('contact_phone', sa.String(length=50), nullable=True),
        sa.Column('website_url', sa.Text(), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=True),
        sa.Column('updated_at', sa.TIMESTAMP(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_store_profiles_id'), 'store_profiles', ['id'], unique=False)

    # ------------------------------------------------------------------
    # 2. Seed exactly one store_profiles row
    # ------------------------------------------------------------------
    store_profile_id = str(uuid.uuid4())
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "INSERT INTO store_profiles (id, business_name) VALUES (:id, :business_name)"
        ),
        {"id": store_profile_id, "business_name": "LEL Marketplace"},
    )

    # ------------------------------------------------------------------
    # 3. Backfill profiles rows for admin users that already have a
    #    seller_profiles row (e.g. a former seller promoted to admin)
    # ------------------------------------------------------------------
    op.execute(
        """
        INSERT INTO profiles (id, name, bio)
        SELECT sp.id, sp.business_name, sp.description
        FROM seller_profiles sp
        JOIN users u ON u.id = sp.id
        WHERE u.role = 'admin'
          AND NOT EXISTS (SELECT 1 FROM profiles p WHERE p.id = sp.id)
        """
    )

    # ------------------------------------------------------------------
    # 4. Reassign existing sellers to customers (seller role is retired)
    # ------------------------------------------------------------------
    op.execute("UPDATE users SET role = 'customer' WHERE role = 'seller'")

    # ------------------------------------------------------------------
    # 5. Narrow users.role enum to ('customer', 'admin')
    #    Safe now that step 4 cleared all 'seller' values.
    # ------------------------------------------------------------------
    op.execute("ALTER TYPE user_roles RENAME TO user_roles_old")
    op.execute("CREATE TYPE user_roles AS ENUM ('customer', 'admin')")
    op.execute(
        "ALTER TABLE users ALTER COLUMN role TYPE user_roles "
        "USING role::text::user_roles"
    )
    op.execute("DROP TYPE user_roles_old")

    # ------------------------------------------------------------------
    # 6. Drop seller_payouts table
    # ------------------------------------------------------------------
    op.drop_index('ix_seller_payouts_seller_id', table_name='seller_payouts')
    op.drop_index('ix_seller_payouts_id', table_name='seller_payouts')
    op.drop_table('seller_payouts')
    op.execute("DROP TYPE IF EXISTS payout_status")

    # ------------------------------------------------------------------
    # 7. Remove real-estate session-request acquisition flow
    # ------------------------------------------------------------------
    op.drop_constraint(
        'properties_acquisition_session_id_fkey', 'properties', type_='foreignkey'
    )
    op.drop_column('properties', 'acquisition_session_id')

    op.drop_constraint(
        'general_inspections_acquisition_session_id_fkey',
        'general_inspections', type_='foreignkey'
    )
    op.drop_column('general_inspections', 'acquisition_session_id')

    op.drop_constraint(
        'general_agreements_acquisition_session_id_fkey',
        'general_agreements', type_='foreignkey'
    )
    op.drop_column('general_agreements', 'acquisition_session_id')

    op.drop_constraint(
        'asset_images_session_request_id_fkey', 'asset_images', type_='foreignkey'
    )
    op.drop_column('asset_images', 'session_request_id')

    op.drop_index('ix_re_session_requests_id', table_name='re_session_requests')
    op.drop_table('re_session_requests')
    op.execute("DROP TYPE IF EXISTS re_session_status")

    # ------------------------------------------------------------------
    # 8. system_settings: drop seller-KYC/notification flags, add
    #    default_grace_period_days (seeded from seller_profiles)
    # ------------------------------------------------------------------
    op.drop_column('system_settings', 'require_seller_kyc')
    op.drop_column('system_settings', 'new_seller_notifications')

    op.add_column(
        'system_settings',
        sa.Column('default_grace_period_days', sa.Integer(), nullable=True),
    )
    op.execute(
        """
        UPDATE system_settings
        SET default_grace_period_days = COALESCE(
            (SELECT default_grace_period_days
             FROM seller_profiles
             WHERE default_grace_period_days IS NOT NULL
             LIMIT 1),
            7
        )
        """
    )

    # ------------------------------------------------------------------
    # 9. seller_profiles table/enums (seller_type, kyc_status) are left
    #    untouched -- dropping them is Phase B scope.
    # ------------------------------------------------------------------


def downgrade() -> None:
    # ------------------------------------------------------------------
    # 8. Restore system_settings columns
    # ------------------------------------------------------------------
    op.drop_column('system_settings', 'default_grace_period_days')
    op.add_column(
        'system_settings',
        sa.Column(
            'new_seller_notifications', sa.Boolean(), nullable=False,
            server_default=sa.text('true'),
        ),
    )
    op.add_column(
        'system_settings',
        sa.Column(
            'require_seller_kyc', sa.Boolean(), nullable=False,
            server_default=sa.text('true'),
        ),
    )

    # ------------------------------------------------------------------
    # 7. Recreate real-estate session-request acquisition flow
    # ------------------------------------------------------------------
    op.execute(
        "CREATE TYPE re_session_status AS ENUM "
        "('pending', 'pending_acquisition', 'acquired', 'declined', "
        "'inspecting', 'processing')"
    )
    op.create_table(
        're_session_requests',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column('title', sa.String(length=255), nullable=True),
        sa.Column('location', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('proposed_price', sa.Numeric(precision=15, scale=2), nullable=True),
        sa.Column('buildings_count', sa.Integer(), nullable=True, server_default='1'),
        sa.Column('property_details', sa.Text(), nullable=True),
        sa.Column(
            'status',
            postgresql.ENUM(
                'pending', 'pending_acquisition', 'acquired', 'declined',
                'inspecting', 'processing', name='re_session_status',
                create_type=False,
            ),
            nullable=True,
        ),
        sa.Column('units_data', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=True),
        sa.Column('updated_at', sa.TIMESTAMP(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], name='re_session_requests_user_id_fkey'),
        sa.PrimaryKeyConstraint('id', name='re_session_requests_pkey'),
    )
    op.create_index(op.f('ix_re_session_requests_id'), 're_session_requests', ['id'], unique=False)

    op.add_column('asset_images', sa.Column('session_request_id', sa.UUID(), nullable=True))
    op.create_foreign_key(
        'asset_images_session_request_id_fkey',
        'asset_images', 're_session_requests',
        ['session_request_id'], ['id'],
        ondelete='CASCADE',
    )

    op.add_column('general_agreements', sa.Column('acquisition_session_id', sa.UUID(), nullable=True))
    op.create_foreign_key(
        'general_agreements_acquisition_session_id_fkey',
        'general_agreements', 're_session_requests',
        ['acquisition_session_id'], ['id'],
    )

    op.add_column('general_inspections', sa.Column('acquisition_session_id', sa.UUID(), nullable=True))
    op.create_foreign_key(
        'general_inspections_acquisition_session_id_fkey',
        'general_inspections', 're_session_requests',
        ['acquisition_session_id'], ['id'],
    )

    op.add_column('properties', sa.Column('acquisition_session_id', sa.UUID(), nullable=True))
    op.create_foreign_key(
        'properties_acquisition_session_id_fkey',
        'properties', 're_session_requests',
        ['acquisition_session_id'], ['id'],
    )

    # ------------------------------------------------------------------
    # 6. Recreate seller_payouts table
    # ------------------------------------------------------------------
    op.execute(
        "CREATE TYPE payout_status AS ENUM "
        "('pending', 'processing', 'completed', 'failed', 'cancelled')"
    )
    op.create_table(
        'seller_payouts',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('seller_id', sa.UUID(), nullable=False),
        sa.Column('amount', sa.DECIMAL(precision=12, scale=2), nullable=False),
        sa.Column('platform_fee', sa.DECIMAL(precision=12, scale=2), nullable=True, server_default='0'),
        sa.Column('net_amount', sa.DECIMAL(precision=12, scale=2), nullable=False),
        sa.Column(
            'status',
            postgresql.ENUM(
                'pending', 'processing', 'completed', 'failed', 'cancelled',
                name='payout_status', create_type=False,
            ),
            nullable=True,
        ),
        sa.Column('transfer_reference', sa.String(length=100), nullable=True),
        sa.Column('paystack_transfer_id', sa.String(length=100), nullable=True),
        sa.Column('recipient_code', sa.String(length=50), nullable=True),
        sa.Column('account_number', sa.String(length=20), nullable=True),
        sa.Column('bank_code', sa.String(length=10), nullable=True),
        sa.Column('bank_name', sa.String(length=100), nullable=True),
        sa.Column('processed_at', sa.TIMESTAMP(), nullable=True),
        sa.Column('failure_reason', sa.Text(), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=True),
        sa.Column('updated_at', sa.TIMESTAMP(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=True),
        sa.ForeignKeyConstraint(['seller_id'], ['seller_profiles.id'], name='seller_payouts_seller_id_fkey'),
        sa.PrimaryKeyConstraint('id', name='seller_payouts_pkey'),
        sa.UniqueConstraint('transfer_reference', name='seller_payouts_transfer_reference_key'),
    )
    op.create_index(op.f('ix_seller_payouts_id'), 'seller_payouts', ['id'], unique=False)
    op.create_index(op.f('ix_seller_payouts_seller_id'), 'seller_payouts', ['seller_id'], unique=False)

    # ------------------------------------------------------------------
    # 5. Widen users.role enum back to ('customer', 'seller', 'admin')
    #    NOTE: cannot recover which 'customer' rows were originally
    #    'seller' -- see data-fidelity note in the module docstring.
    # ------------------------------------------------------------------
    op.execute("ALTER TYPE user_roles RENAME TO user_roles_old")
    op.execute("CREATE TYPE user_roles AS ENUM ('customer', 'seller', 'admin')")
    op.execute(
        "ALTER TABLE users ALTER COLUMN role TYPE user_roles "
        "USING role::text::user_roles"
    )
    op.execute("DROP TYPE user_roles_old")

    # ------------------------------------------------------------------
    # 4 & 3. Role reassignment and profiles backfill are not reversed --
    #    intentional, accepted limitation (see module docstring).
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # 2 & 1. Drop store_profiles (row + table)
    # ------------------------------------------------------------------
    op.drop_index(op.f('ix_store_profiles_id'), table_name='store_profiles')
    op.drop_table('store_profiles')
