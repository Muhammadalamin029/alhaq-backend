"""remove_phone_dealer

Revision ID: a1b2c3d4e5f6
Revises: 4532f3ec3c7f
Create Date: 2026-06-03 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'a1b2c3d4e5f6'
down_revision = '4532f3ec3c7f'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. Drop phone_units table (references phones)
    # ------------------------------------------------------------------
    op.drop_index(op.f('ix_phone_units_id'), table_name='phone_units')
    op.drop_table('phone_units')

    # ------------------------------------------------------------------
    # 2. Remove phone_id FK and column from asset_images
    # ------------------------------------------------------------------
    op.drop_constraint('asset_images_phone_id_fkey', 'asset_images', type_='foreignkey')
    op.drop_column('asset_images', 'phone_id')

    # ------------------------------------------------------------------
    # 3. Drop phones table
    # ------------------------------------------------------------------
    op.drop_index(op.f('ix_phones_id'), table_name='phones')
    op.drop_table('phones')

    # ------------------------------------------------------------------
    # 4. Drop enum types that belonged exclusively to the phone tables
    # ------------------------------------------------------------------
    op.execute("DROP TYPE IF EXISTS phone_listing_status")
    op.execute("DROP TYPE IF EXISTS phone_unit_status")

    # ------------------------------------------------------------------
    # 5. Remove 'phone_dealer' from seller_type enum
    #    Re-categorise existing phone dealers as retailers first
    # ------------------------------------------------------------------
    op.execute(
        "UPDATE seller_profiles SET seller_type = 'retailer' WHERE seller_type = 'phone_dealer'"
    )
    op.execute("ALTER TYPE seller_type RENAME TO seller_type_old")
    op.execute(
        "CREATE TYPE seller_type AS ENUM ('retailer', 'car_dealer', 'real_agent')"
    )
    op.execute(
        "ALTER TABLE seller_profiles "
        "ALTER COLUMN seller_type TYPE seller_type "
        "USING seller_type::text::seller_type"
    )
    op.execute("DROP TYPE seller_type_old")

    # ------------------------------------------------------------------
    # 6. Remove 'phone' from asset_category enum
    #    Delete orphaned phone inspections/agreements first, then swap enum
    # ------------------------------------------------------------------
    op.execute("DELETE FROM general_agreements WHERE asset_type = 'phone'")
    op.execute("DELETE FROM general_inspections WHERE asset_type = 'phone'")
    op.execute("ALTER TYPE asset_category RENAME TO asset_category_old")
    op.execute(
        "CREATE TYPE asset_category AS ENUM ('automotive', 'property')"
    )
    op.execute(
        "ALTER TABLE general_inspections "
        "ALTER COLUMN asset_type TYPE asset_category "
        "USING asset_type::text::asset_category"
    )
    op.execute(
        "ALTER TABLE general_agreements "
        "ALTER COLUMN asset_type TYPE asset_category "
        "USING asset_type::text::asset_category"
    )
    op.execute("DROP TYPE asset_category_old")

    # ------------------------------------------------------------------
    # 7. Remove 'phone_approved' / 'phone_rejected' from notification_type enum
    #    Delete any existing rows first to avoid cast errors
    # ------------------------------------------------------------------
    op.execute(
        "DELETE FROM notifications WHERE type IN ('phone_approved', 'phone_rejected')"
    )
    op.execute("ALTER TYPE notification_type RENAME TO notification_type_old")
    op.execute("""
        CREATE TYPE notification_type AS ENUM (
            'order_confirmed', 'order_processing', 'order_shipped', 'order_delivered', 'order_cancelled',
            'payment_successful', 'payment_failed',
            'account_verified', 'password_changed', 'profile_updated',
            'wishlist_item_back_in_stock', 'system_announcement', 'promotional_offer',
            'car_approved', 'car_rejected',
            'inspection_scheduled', 'inspection_confirmed', 'inspection_rejected', 'inspection_complete',
            'property_acquired',
            'agreement_completed', 'agreement_created', 'agreement_approved',
            'agreement_rejected', 'agreement_update',
            'installment_paid', 'payment_reminder', 'installment_due', 'installment_defaulted'
        )
    """)
    op.execute(
        "ALTER TABLE notifications "
        "ALTER COLUMN type TYPE notification_type "
        "USING type::text::notification_type"
    )
    op.execute("DROP TYPE notification_type_old")


def downgrade() -> None:
    # ------------------------------------------------------------------
    # 7. Restore phone_approved / phone_rejected in notification_type
    # ------------------------------------------------------------------
    op.execute("ALTER TYPE notification_type RENAME TO notification_type_old")
    op.execute("""
        CREATE TYPE notification_type AS ENUM (
            'order_confirmed', 'order_processing', 'order_shipped', 'order_delivered', 'order_cancelled',
            'payment_successful', 'payment_failed',
            'account_verified', 'password_changed', 'profile_updated',
            'wishlist_item_back_in_stock', 'system_announcement', 'promotional_offer',
            'car_approved', 'car_rejected',
            'phone_approved', 'phone_rejected',
            'inspection_scheduled', 'inspection_confirmed', 'inspection_rejected', 'inspection_complete',
            'property_acquired',
            'agreement_completed', 'agreement_created', 'agreement_approved',
            'agreement_rejected', 'agreement_update',
            'installment_paid', 'payment_reminder', 'installment_due', 'installment_defaulted'
        )
    """)
    op.execute(
        "ALTER TABLE notifications "
        "ALTER COLUMN type TYPE notification_type "
        "USING type::text::notification_type"
    )
    op.execute("DROP TYPE notification_type_old")

    # ------------------------------------------------------------------
    # 6. Restore 'phone' in asset_category enum
    # ------------------------------------------------------------------
    op.execute("ALTER TYPE asset_category RENAME TO asset_category_old")
    op.execute(
        "CREATE TYPE asset_category AS ENUM ('automotive', 'property', 'phone')"
    )
    op.execute(
        "ALTER TABLE general_inspections "
        "ALTER COLUMN asset_type TYPE asset_category "
        "USING asset_type::text::asset_category"
    )
    op.execute(
        "ALTER TABLE general_agreements "
        "ALTER COLUMN asset_type TYPE asset_category "
        "USING asset_type::text::asset_category"
    )
    op.execute("DROP TYPE asset_category_old")

    # ------------------------------------------------------------------
    # 5. Restore 'phone_dealer' in seller_type enum
    # ------------------------------------------------------------------
    op.execute("ALTER TYPE seller_type RENAME TO seller_type_old")
    op.execute(
        "CREATE TYPE seller_type AS ENUM ('retailer', 'car_dealer', 'real_agent', 'phone_dealer')"
    )
    op.execute(
        "ALTER TABLE seller_profiles "
        "ALTER COLUMN seller_type TYPE seller_type "
        "USING seller_type::text::seller_type"
    )
    op.execute("DROP TYPE seller_type_old")

    # ------------------------------------------------------------------
    # 4. Recreate phone enum types
    # ------------------------------------------------------------------
    op.execute(
        "CREATE TYPE phone_unit_status AS ENUM "
        "('available', 'inspected', 'awaiting_payment', 'sold', 'reserved')"
    )
    op.execute(
        "CREATE TYPE phone_listing_status AS ENUM ('available', 'out_of_stock')"
    )

    # ------------------------------------------------------------------
    # 3. Recreate phones table
    # ------------------------------------------------------------------
    op.create_table(
        'phones',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('seller_id', sa.UUID(), nullable=False),
        sa.Column('brand', sa.String(length=100), nullable=False),
        sa.Column('model', sa.String(length=100), nullable=False),
        sa.Column('specs', sa.Text(), nullable=True),
        sa.Column('price', sa.Numeric(precision=15, scale=2), nullable=False),
        sa.Column('min_deposit_percentage', sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column('status', postgresql.ENUM('available', 'out_of_stock', name='phone_listing_status', create_type=False), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=True),
        sa.Column('updated_at', sa.TIMESTAMP(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=True),
        sa.ForeignKeyConstraint(['seller_id'], ['seller_profiles.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_phones_id'), 'phones', ['id'], unique=False)

    # ------------------------------------------------------------------
    # 2. Re-add phone_id to asset_images
    # ------------------------------------------------------------------
    op.add_column('asset_images', sa.Column('phone_id', sa.UUID(), nullable=True))
    op.create_foreign_key(
        'asset_images_phone_id_fkey',
        'asset_images', 'phones',
        ['phone_id'], ['id'],
        ondelete='CASCADE'
    )

    # ------------------------------------------------------------------
    # 1. Recreate phone_units table
    # ------------------------------------------------------------------
    op.create_table(
        'phone_units',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('phone_id', sa.UUID(), nullable=False),
        sa.Column('imei', sa.String(length=100), nullable=False),
        sa.Column('color', sa.String(length=50), nullable=True),
        sa.Column('grade', sa.String(length=20), nullable=True),
        sa.Column('battery_health', sa.Integer(), nullable=True),
        sa.Column('status', postgresql.ENUM('available', 'inspected', 'awaiting_payment', 'sold', 'reserved', name='phone_unit_status', create_type=False), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=True),
        sa.Column('updated_at', sa.TIMESTAMP(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=True),
        sa.ForeignKeyConstraint(['phone_id'], ['phones.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('imei'),
    )
    op.create_index(op.f('ix_phone_units_id'), 'phone_units', ['id'], unique=False)
