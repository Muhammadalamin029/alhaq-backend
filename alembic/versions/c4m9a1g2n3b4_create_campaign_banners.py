"""create campaign_banners table

Revision ID: c4m9a1g2n3b4
Revises: b1d2e3f4a5c6
Create Date: 2026-09-25 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c4m9a1g2n3b4'
down_revision = 'b1d2e3f4a5c6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Idempotent: the table may already exist (created at runtime via
    # checkfirst on dev databases), so only create it when missing.
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("campaign_banners"):
        return
    op.create_table(
        'campaign_banners',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('title', sa.String(length=255), nullable=False, server_default=''),
        sa.Column('subtitle', sa.String(length=500), nullable=True),
        sa.Column('image_url', sa.Text(), nullable=False),
        sa.Column('cta_text', sa.String(length=100), nullable=True),
        sa.Column('cta_link', sa.String(length=500), nullable=True),
        sa.Column('display_order', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('created_at', sa.TIMESTAMP(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=True),
        sa.Column('updated_at', sa.TIMESTAMP(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_campaign_banners_id', 'campaign_banners', ['id'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_campaign_banners_id', table_name='campaign_banners')
    op.drop_table('campaign_banners')
