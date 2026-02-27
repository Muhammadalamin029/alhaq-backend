"""Sync automotive and real estate models

Revision ID: 24845d1f2b8f
Revises: 883e5bdd303f
Create Date: 2026-02-27 02:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '24845d1f2b8f'
down_revision = '883e5bdd303f'
branch_labels = None
depends_on = None

def upgrade() -> None:
    # Check for existing tables to avoid duplicate errors
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    existing_tables = inspector.get_table_names()

    # Enums
    # Create seller_type enum if it doesn't exist
    result = connection.execute(sa.text("SELECT 1 FROM pg_type WHERE typname = 'seller_type'"))
    if not result.fetchone():
        op.execute("CREATE TYPE seller_type AS ENUM ('retailer', 'car_dealer', 'real_agent')")

    # Create car_listing_status enum
    result = connection.execute(sa.text("SELECT 1 FROM pg_type WHERE typname = 'car_listing_status'"))
    if not result.fetchone():
        op.execute("CREATE TYPE car_listing_status AS ENUM ('available', 'out_of_stock')")

    # Create unit_status enum
    result = connection.execute(sa.text("SELECT 1 FROM pg_type WHERE typname = 'unit_status'"))
    if not result.fetchone():
        op.execute("CREATE TYPE unit_status AS ENUM ('available', 'inspected', 'awaiting_payment', 'sold', 'reserved')")

    # Create inspection_status enum
    result = connection.execute(sa.text("SELECT 1 FROM pg_type WHERE typname = 'inspection_status'"))
    if not result.fetchone():
        op.execute("CREATE TYPE inspection_status AS ENUM ('scheduled', 'completed', 'rejected', 'agreement_pending', 'agreement_accepted')")

    # Create listing_type enum
    result = connection.execute(sa.text("SELECT 1 FROM pg_type WHERE typname = 'listing_type'"))
    if not result.fetchone():
        op.execute("CREATE TYPE listing_type AS ENUM ('sale', 'rental', 'professional')")

    # Create property_status enum
    result = connection.execute(sa.text("SELECT 1 FROM pg_type WHERE typname = 'property_status'"))
    if not result.fetchone():
        op.execute("CREATE TYPE property_status AS ENUM ('available', 'pending_inspection', 'property_inspected', 'awaiting_payment', 'reserved', 'sold', 'rented', 'under_financing')")

    # Create re_session_status enum
    result = connection.execute(sa.text("SELECT 1 FROM pg_type WHERE typname = 're_session_status'"))
    if not result.fetchone():
        op.execute("CREATE TYPE re_session_status AS ENUM ('pending', 'pending_acquisition', 'acquired', 'declined')")

    # Create financing_plan_type enum
    result = connection.execute(sa.text("SELECT 1 FROM pg_type WHERE typname = 'financing_plan_type'"))
    if not result.fetchone():
        op.execute("CREATE TYPE financing_plan_type AS ENUM ('structured', 'flexible')")

    # Create agreement_status enum
    result = connection.execute(sa.text("SELECT 1 FROM pg_type WHERE typname = 'agreement_status'"))
    if not result.fetchone():
        op.execute("CREATE TYPE agreement_status AS ENUM ('pending_deposit', 'active', 'completed', 'defaulted', 'cancelled')")

    # Create asset_payment_type enum
    result = connection.execute(sa.text("SELECT 1 FROM pg_type WHERE typname = 'asset_payment_type'"))
    if not result.fetchone():
        op.execute("CREATE TYPE asset_payment_type AS ENUM ('deposit', 'installment', 'full_pay')")

    # Create asset_payment_status enum
    result = connection.execute(sa.text("SELECT 1 FROM pg_type WHERE typname = 'asset_payment_status'"))
    if not result.fetchone():
        op.execute("CREATE TYPE asset_payment_status AS ENUM ('success', 'failed', 'pending')")

    # Update seller_profiles table
    columns = [col['name'] for col in inspector.get_columns('seller_profiles')]
    if 'seller_type' not in columns:
        op.add_column('seller_profiles', sa.Column('seller_type', sa.Enum('retailer', 'car_dealer', 'real_agent', name='seller_type'), nullable=True))

    # Create tables
    if 'cars' not in existing_tables:
        op.create_table('cars',
            sa.Column('id', sa.UUID(), nullable=False),
            sa.Column('seller_id', sa.UUID(), nullable=False),
            sa.Column('brand', sa.String(length=100), nullable=False),
            sa.Column('model', sa.String(length=100), nullable=False),
            sa.Column('year', sa.Integer(), nullable=False),
            sa.Column('price', sa.Numeric(precision=15, scale=2), nullable=False),
            sa.Column('min_deposit_percentage', sa.Numeric(precision=5, scale=2), nullable=True),
            sa.Column('status', sa.Enum('available', 'out_of_stock', name='car_listing_status'), nullable=True),
            sa.Column('created_at', sa.TIMESTAMP(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=True),
            sa.Column('updated_at', sa.TIMESTAMP(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=True),
            sa.ForeignKeyConstraint(['seller_id'], ['seller_profiles.id'], ),
            sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_cars_id'), 'cars', ['id'], unique=False)

    if 'car_units' not in existing_tables:
        op.create_table('car_units',
            sa.Column('id', sa.UUID(), nullable=False),
            sa.Column('car_id', sa.UUID(), nullable=False),
            sa.Column('vin', sa.String(length=100), nullable=False),
            sa.Column('mileage', sa.Integer(), nullable=False),
            sa.Column('color', sa.String(length=50), nullable=True),
            sa.Column('status', sa.Enum('available', 'inspected', 'awaiting_payment', 'sold', 'reserved', name='unit_status'), nullable=True),
            sa.Column('created_at', sa.TIMESTAMP(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=True),
            sa.Column('updated_at', sa.TIMESTAMP(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=True),
            sa.ForeignKeyConstraint(['car_id'], ['cars.id'], ),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('vin')
        )
        op.create_index(op.f('ix_car_units_id'), 'car_units', ['id'], unique=False)

    if 'car_inspections' not in existing_tables:
        op.create_table('car_inspections',
            sa.Column('id', sa.UUID(), nullable=False),
            sa.Column('car_id', sa.UUID(), nullable=False),
            sa.Column('unit_id', sa.UUID(), nullable=True),
            sa.Column('user_id', sa.UUID(), nullable=False),
            sa.Column('inspection_date', sa.TIMESTAMP(), nullable=False),
            sa.Column('notes', sa.Text(), nullable=True),
            sa.Column('agreed_price', sa.Numeric(precision=15, scale=2), nullable=True),
            sa.Column('status', sa.Enum('scheduled', 'completed', 'rejected', 'agreement_pending', 'agreement_accepted', name='inspection_status'), nullable=True),
            sa.Column('created_at', sa.TIMESTAMP(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=True),
            sa.ForeignKeyConstraint(['car_id'], ['cars.id'], ),
            sa.ForeignKeyConstraint(['unit_id'], ['car_units.id'], ),
            sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
            sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_car_inspections_id'), 'car_inspections', ['id'], unique=False)

    if 'properties' not in existing_tables:
        op.create_table('properties',
            sa.Column('id', sa.UUID(), nullable=False),
            sa.Column('seller_id', sa.UUID(), nullable=False),
            sa.Column('title', sa.String(length=255), nullable=False),
            sa.Column('description', sa.Text(), nullable=True),
            sa.Column('price', sa.Numeric(precision=15, scale=2), nullable=False),
            sa.Column('location', sa.String(length=255), nullable=False),
            sa.Column('listing_type', sa.Enum('sale', 'rental', 'professional', name='listing_type'), nullable=True),
            sa.Column('status', sa.Enum('available', 'pending_inspection', 'property_inspected', 'awaiting_payment', 'reserved', 'sold', 'rented', 'under_financing', name='property_status'), nullable=True),
            sa.Column('created_at', sa.TIMESTAMP(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=True),
            sa.Column('updated_at', sa.TIMESTAMP(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=True),
            sa.ForeignKeyConstraint(['seller_id'], ['seller_profiles.id'], ),
            sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_properties_id'), 'properties', ['id'], unique=False)

    if 're_session_requests' not in existing_tables:
        op.create_table('re_session_requests',
            sa.Column('id', sa.UUID(), nullable=False),
            sa.Column('user_id', sa.UUID(), nullable=False),
            sa.Column('location', sa.String(length=255), nullable=False),
            sa.Column('property_details', sa.Text(), nullable=False),
            sa.Column('status', sa.Enum('pending', 'pending_acquisition', 'acquired', 'declined', name='re_session_status'), nullable=True),
            sa.Column('created_at', sa.TIMESTAMP(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=True),
            sa.Column('updated_at', sa.TIMESTAMP(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=True),
            sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
            sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_re_session_requests_id'), 're_session_requests', ['id'], unique=False)

    if 'car_agreements' not in existing_tables:
        op.create_table('car_agreements',
            sa.Column('id', sa.UUID(), nullable=False),
            sa.Column('user_id', sa.UUID(), nullable=False),
            sa.Column('car_id', sa.UUID(), nullable=False),
            sa.Column('unit_id', sa.UUID(), nullable=True),
            sa.Column('inspection_id', sa.UUID(), nullable=True),
            sa.Column('order_id', sa.UUID(), nullable=True),
            sa.Column('total_price', sa.Numeric(precision=15, scale=2), nullable=False),
            sa.Column('deposit_paid', sa.Numeric(precision=15, scale=2), nullable=False),
            sa.Column('remaining_balance', sa.Numeric(precision=15, scale=2), nullable=False),
            sa.Column('plan_type', sa.Enum('structured', 'flexible', name='financing_plan_type'), nullable=False),
            sa.Column('duration_months', sa.Integer(), nullable=True),
            sa.Column('monthly_installment', sa.Numeric(precision=15, scale=2), nullable=True),
            sa.Column('final_deadline', sa.TIMESTAMP(), nullable=True),
            sa.Column('next_due_date', sa.TIMESTAMP(), nullable=True),
            sa.Column('status', sa.Enum('pending_deposit', 'active', 'completed', 'defaulted', 'cancelled', name='agreement_status'), nullable=True),
            sa.Column('created_at', sa.TIMESTAMP(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=True),
            sa.Column('updated_at', sa.TIMESTAMP(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=True),
            sa.ForeignKeyConstraint(['car_id'], ['cars.id'], ),
            sa.ForeignKeyConstraint(['inspection_id'], ['car_inspections.id'], ),
            sa.ForeignKeyConstraint(['order_id'], ['orders.id'], ),
            sa.ForeignKeyConstraint(['unit_id'], ['car_units.id'], ),
            sa.ForeignKeyConstraint(['user_id'], ['profiles.id'], ),
            sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_car_agreements_id'), 'car_agreements', ['id'], unique=False)

    if 'property_agreements' not in existing_tables:
        op.create_table('property_agreements',
            sa.Column('id', sa.UUID(), nullable=False),
            sa.Column('user_id', sa.UUID(), nullable=False),
            sa.Column('property_id', sa.UUID(), nullable=False),
            sa.Column('order_id', sa.UUID(), nullable=True),
            sa.Column('total_price', sa.Numeric(precision=15, scale=2), nullable=False),
            sa.Column('deposit_paid', sa.Numeric(precision=15, scale=2), nullable=False),
            sa.Column('remaining_balance', sa.Numeric(precision=15, scale=2), nullable=False),
            sa.Column('plan_type', sa.Enum('structured', 'flexible', name='financing_plan_type'), nullable=False),
            sa.Column('duration_months', sa.Integer(), nullable=True),
            sa.Column('monthly_installment', sa.Numeric(precision=15, scale=2), nullable=True),
            sa.Column('final_deadline', sa.TIMESTAMP(), nullable=True),
            sa.Column('next_due_date', sa.TIMESTAMP(), nullable=True),
            sa.Column('status', sa.Enum('pending_deposit', 'active', 'completed', 'defaulted', 'cancelled', name='agreement_status'), nullable=True),
            sa.Column('created_at', sa.TIMESTAMP(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=True),
            sa.Column('updated_at', sa.TIMESTAMP(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=True),
            sa.ForeignKeyConstraint(['order_id'], ['orders.id'], ),
            sa.ForeignKeyConstraint(['property_id'], ['properties.id'], ),
            sa.ForeignKeyConstraint(['user_id'], ['profiles.id'], ),
            sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_property_agreements_id'), 'property_agreements', ['id'], unique=False)

    if 'car_payments' not in existing_tables:
        op.create_table('car_payments',
            sa.Column('id', sa.UUID(), nullable=False),
            sa.Column('agreement_id', sa.UUID(), nullable=False),
            sa.Column('user_id', sa.UUID(), nullable=False),
            sa.Column('amount', sa.Numeric(precision=15, scale=2), nullable=False),
            sa.Column('paystack_ref', sa.String(length=100), nullable=False),
            sa.Column('payment_type', sa.Enum('deposit', 'installment', 'full_pay', name='asset_payment_type'), nullable=False),
            sa.Column('status', sa.Enum('success', 'failed', 'pending', name='asset_payment_status'), nullable=True),
            sa.Column('created_at', sa.TIMESTAMP(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=True),
            sa.ForeignKeyConstraint(['agreement_id'], ['car_agreements.id'], ),
            sa.ForeignKeyConstraint(['user_id'], ['profiles.id'], ),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('paystack_ref')
        )
        op.create_index(op.f('ix_car_payments_id'), 'car_payments', ['id'], unique=False)

    if 'property_payments' not in existing_tables:
        op.create_table('property_payments',
            sa.Column('id', sa.UUID(), nullable=False),
            sa.Column('agreement_id', sa.UUID(), nullable=False),
            sa.Column('user_id', sa.UUID(), nullable=False),
            sa.Column('amount', sa.Numeric(precision=15, scale=2), nullable=False),
            sa.Column('paystack_ref', sa.String(length=100), nullable=False),
            sa.Column('payment_type', sa.Enum('deposit', 'installment', 'full_pay', name='asset_payment_type'), nullable=False),
            sa.Column('status', sa.Enum('success', 'failed', 'pending', name='asset_payment_status'), nullable=True),
            sa.Column('created_at', sa.TIMESTAMP(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=True),
            sa.ForeignKeyConstraint(['agreement_id'], ['property_agreements.id'], ),
            sa.ForeignKeyConstraint(['user_id'], ['profiles.id'], ),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('paystack_ref')
        )
        op.create_index(op.f('ix_property_payments_id'), 'property_payments', ['id'], unique=False)

    if 'audit_logs' not in existing_tables:
        op.create_table('audit_logs',
            sa.Column('id', sa.UUID(), nullable=False),
            sa.Column('admin_id', sa.UUID(), nullable=False),
            sa.Column('target_id', sa.UUID(), nullable=True),
            sa.Column('action', sa.String(length=255), nullable=False),
            sa.Column('details', sa.Text(), nullable=True),
            sa.Column('timestamp', sa.TIMESTAMP(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=True),
            sa.ForeignKeyConstraint(['admin_id'], ['users.id'], ),
            sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_audit_logs_id'), 'audit_logs', ['id'], unique=False)

def downgrade() -> None:
    op.drop_column('seller_profiles', 'seller_type')
    op.drop_table('audit_logs')
    op.drop_table('property_payments')
    op.drop_table('car_payments')
    op.drop_table('property_agreements')
    op.drop_table('car_agreements')
    op.drop_table('re_session_requests')
    op.drop_table('properties')
    op.drop_table('car_inspections')
    op.drop_table('car_units')
    op.drop_table('cars')
    # Types removal - careful with dependencies
    op.execute("DROP TYPE IF EXISTS asset_payment_status")
    op.execute("DROP TYPE IF EXISTS asset_payment_type")
    op.execute("DROP TYPE IF EXISTS agreement_status")
    op.execute("DROP TYPE IF EXISTS financing_plan_type")
    op.execute("DROP TYPE IF EXISTS re_session_status")
    op.execute("DROP TYPE IF EXISTS property_status")
    op.execute("DROP TYPE IF EXISTS listing_type")
    op.execute("DROP TYPE IF EXISTS inspection_status")
    op.execute("DROP TYPE IF EXISTS unit_status")
    op.execute("DROP TYPE IF EXISTS car_listing_status")
    op.execute("DROP TYPE IF EXISTS seller_type")
