"""add session_id to property and inspection

Revision ID: f2b3c4d5e6f7
Revises: f1a2b3c4d5e6
Create Date: 2026-03-23 20:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'f2b3c4d5e6f7'
down_revision = 'f1a2b3c4d5e6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('properties', sa.Column('acquisition_session_id', sa.UUID(), sa.ForeignKey('re_session_requests.id'), nullable=True))
    op.add_column('general_inspections', sa.Column('acquisition_session_id', sa.UUID(), sa.ForeignKey('re_session_requests.id'), nullable=True))
    op.add_column('general_agreements', sa.Column('acquisition_session_id', sa.UUID(), sa.ForeignKey('re_session_requests.id'), nullable=True))


def downgrade() -> None:
    op.drop_column('general_agreements', 'acquisition_session_id')
    op.drop_column('general_inspections', 'acquisition_session_id')
    op.drop_column('properties', 'acquisition_session_id')
