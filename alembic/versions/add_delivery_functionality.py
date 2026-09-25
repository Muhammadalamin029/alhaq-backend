"""add_delivery_functionality

Revision ID: d1e2f3a4b5c6
Revises: c3d4e5f6a7b8
Create Date: 2026-09-13 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import UUID
import uuid


# revision identifiers, used by Alembic.
revision = 'd1e2f3a4b5c6'
down_revision = '0c5cf35fd55a'
branch_labels = None
depends_on = None


# 36 Nigerian states + FCT
NIGERIAN_STATES = [
    "Abia", "Adamawa", "Akwa Ibom", "Anambra", "Bauchi", "Bayelsa", "Benue", "Borno",
    "Cross River", "Delta", "Ebonyi", "Edo", "Ekiti", "Enugu", "FCT", "Gombe", "Imo",
    "Jigawa", "Kaduna", "Kano", "Katsina", "Kebbi", "Kogi", "Kwara", "Lagos", "Nasarawa",
    "Niger", "Ogun", "Ondo", "Osun", "Oyo", "Plateau", "Rivers", "Sokoto", "Taraba", "Yobe", "Zamfara"
]


def upgrade() -> None:
    # Idempotent: every step is guarded so re-running on databases that
    # already have this schema (but never recorded the revision) is a no-op.
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())

    def has_column(table: str, column: str) -> bool:
        if table not in tables:
            return False
        try:
            return column in {c["name"] for c in inspector.get_columns(table)}
        except Exception:
            return False

    def has_type(name: str) -> bool:
        try:
            row = op.get_bind().execute(
                sa.text("SELECT 1 FROM pg_type WHERE typname = :name")
            ).first()
            return row is not None
        except Exception:
            return False

    # Create delivery_states table (+ seed) only when missing
    if "delivery_states" not in tables:
        op.create_table(
            'delivery_states',
            sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
            sa.Column('state_name', sa.String(100), nullable=False, unique=True),
            sa.Column('delivery_price', sa.Numeric(15, 2), nullable=True),
            sa.Column('is_active', sa.Boolean(), default=True),
            sa.Column('created_at', sa.TIMESTAMP(), server_default=sa.text('CURRENT_TIMESTAMP')),
            sa.Column('updated_at', sa.TIMESTAMP(), server_default=sa.text('CURRENT_TIMESTAMP'), onupdate=sa.text('CURRENT_TIMESTAMP'))
        )

        # Seed delivery_states with all 36 Nigerian states
        from sqlalchemy.sql import table, column
        from sqlalchemy import insert

        delivery_states_table = table('delivery_states',
            column('id'),
            column('state_name'),
            column('delivery_price'),
            column('is_active')
        )

        op.bulk_insert(delivery_states_table, [
            {'id': str(uuid.uuid4()), 'state_name': state, 'delivery_price': None, 'is_active': True}
            for state in NIGERIAN_STATES
        ])

    # Add delivery_state_id to addresses table
    if not has_column("addresses", "delivery_state_id"):
        op.add_column('addresses', sa.Column('delivery_state_id', UUID(as_uuid=True), nullable=True))
        op.create_foreign_key('fk_addresses_delivery_state', 'addresses', 'delivery_states', ['delivery_state_id'], ['id'])

    # Get FCT state ID for default
    connection = op.get_bind()
    result = connection.execute(sa.text("SELECT id FROM delivery_states WHERE state_name = 'FCT'"))
    fct_id = result.scalar()

    # Set existing addresses to FCT as default
    if fct_id:
        op.execute(sa.text(f"UPDATE addresses SET delivery_state_id = '{fct_id}' WHERE delivery_state_id IS NULL"))

    # Add delivery fields to orders table
    if not has_type("delivery_type"):
        op.execute("CREATE TYPE delivery_type AS ENUM ('pickup', 'delivery')")
    if not has_column("orders", "delivery_type"):
        op.add_column('orders', sa.Column('delivery_type', sa.Enum('pickup', 'delivery', name='delivery_type', create_type=False), default='delivery'))
    if not has_column("orders", "delivery_fee"):
        op.add_column('orders', sa.Column('delivery_fee', sa.Numeric(15, 2), default=0))
    if not has_column("orders", "pickup_location"):
        op.add_column('orders', sa.Column('pickup_location', sa.Text(), nullable=True))

    # Add delivery settings to system_settings table
    if not has_column("system_settings", "base_delivery_price"):
        op.add_column('system_settings', sa.Column('base_delivery_price', sa.Numeric(15, 2), default=0))
    if not has_column("system_settings", "store_pickup_location"):
        op.add_column('system_settings', sa.Column('store_pickup_location', sa.Text(), nullable=True))
    if not has_column("system_settings", "store_pickup_address"):
        op.add_column('system_settings', sa.Column('store_pickup_address', sa.Text(), nullable=True))


def downgrade() -> None:
    # Remove delivery settings from system_settings
    op.drop_column('system_settings', 'store_pickup_address')
    op.drop_column('system_settings', 'store_pickup_location')
    op.drop_column('system_settings', 'base_delivery_price')

    # Remove delivery fields from orders
    op.drop_column('orders', 'pickup_location')
    op.drop_column('orders', 'delivery_fee')
    op.drop_column('orders', 'delivery_type')
    op.execute("DROP TYPE delivery_type")

    # Remove delivery_state_id from addresses
    op.drop_constraint('fk_addresses_delivery_state', 'addresses', type_='foreignkey')
    op.drop_column('addresses', 'delivery_state_id')

    # Drop delivery_states table
    op.drop_table('delivery_states')
