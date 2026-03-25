"""Add PropertyUnits and buildings_count

Revision ID: 68157138703e
Revises: 67f87d811ff6
Create Date: 2026-03-24 23:18:12.878725

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '68157138703e'
down_revision = '67f87d811ff6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Add buildings_count to properties
    op.add_column('properties', sa.Column('buildings_count', sa.Integer(), nullable=True, server_default='1'))

    # 2. property_unit_status enum is handled via create_table with create_type=False or by existing type

    # 3. Create property_units table
    op.create_table(
        'property_units',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('property_id', sa.UUID(), nullable=False),
        sa.Column('unit_name', sa.String(length=100), nullable=True),
        sa.Column('unit_number', sa.String(length=50), nullable=True),
        sa.Column('status', sa.Enum('available', 'inspected', 'awaiting_payment', 'sold', 'reserved', 'acquired', name='property_unit_status', create_type=False), nullable=True, server_default='available'),
        sa.Column('created_at', sa.TIMESTAMP(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=True),
        sa.Column('updated_at', sa.TIMESTAMP(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=True),
        sa.ForeignKeyConstraint(['property_id'], ['properties.id']),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_property_units_id'), 'property_units', ['id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_property_units_id'), table_name='property_units')
    op.drop_table('property_units')
    op.execute("DROP TYPE property_unit_status")
    op.drop_column('properties', 'buildings_count')
