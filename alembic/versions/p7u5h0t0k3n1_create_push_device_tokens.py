"""create push_device_tokens table

Revision ID: p7u5h0t0k3n1
Revises: c4m9a1g2n3b4
Create Date: 2026-09-25 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'p7u5h0t0k3n1'
down_revision = 'c4m9a1g2n3b4'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Idempotent: the table may already exist (created at runtime via
    # checkfirst on dev databases), so only create it when missing.
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("push_device_tokens"):
        return
    op.create_table(
        'push_device_tokens',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column('expo_push_token', sa.String(length=255), nullable=False),
        sa.Column('platform', sa.String(length=16), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('created_at', sa.TIMESTAMP(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=True),
        sa.Column('updated_at', sa.TIMESTAMP(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_push_device_tokens_id', 'push_device_tokens', ['id'], unique=False)
    op.create_index('ix_push_device_tokens_user_id', 'push_device_tokens', ['user_id'], unique=False)
    op.create_index('ix_push_device_tokens_token', 'push_device_tokens', ['expo_push_token'], unique=True)


def downgrade() -> None:
    op.drop_index('ix_push_device_tokens_token', table_name='push_device_tokens')
    op.drop_index('ix_push_device_tokens_user_id', table_name='push_device_tokens')
    op.drop_index('ix_push_device_tokens_id', table_name='push_device_tokens')
    op.drop_table('push_device_tokens')
