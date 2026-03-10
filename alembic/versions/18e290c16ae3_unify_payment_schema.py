"""unify_payment_schema

Revision ID: 18e290c16ae3
Revises: 445ee9bfa76b
Create Date: 2026-03-08 12:00:15.123456

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '18e290c16ae3'
down_revision = '445ee9bfa76b'
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    # 1. Update payment_category enum (Postgres-specific)
    # Check if 'full_pay' exists
    res = conn.execute(sa.text("""
        SELECT 1 FROM pg_enum 
        WHERE enumtypid = (SELECT oid FROM pg_type WHERE typname = 'payment_category') 
        AND enumlabel = 'full_pay'
    """)).fetchone()
    
    if not res:
        # Note: ALTER TYPE ... ADD VALUE cannot be executed within a transaction block
        # Alembic by default wraps upgrade() in a transaction.
        # However, op.execute("COMMIT") can be used to break out, but that can lead to inconsistent state.
        # But for Enum addition it is often necessary.
        op.execute("ALTER TYPE payment_category ADD VALUE 'full_pay'")

    # 2. Add asset_payment_type enum
    res = conn.execute(sa.text("SELECT 1 FROM pg_type WHERE typname = 'asset_payment_type'")).fetchone()
    if not res:
        op.execute("CREATE TYPE asset_payment_type AS ENUM ('order', 'deposit', 'installment', 'full_pay')")
    
    # 3. Add column 'payment_type'
    res = conn.execute(sa.text("SELECT 1 FROM information_schema.columns WHERE table_name='payments' AND column_name='payment_type'")).fetchone()
    if not res:
        op.add_column('payments', sa.Column('payment_type', sa.Enum('order', 'deposit', 'installment', 'full_pay', name='asset_payment_type'), nullable=True))

    # 4. Alter payment_method column to be nullable
    op.alter_column('payments', 'payment_method',
               existing_type=sa.VARCHAR(length=50),
               nullable=True,
               existing_nullable=False)


def downgrade() -> None:
    op.drop_column('payments', 'payment_type')
    op.execute("DROP TYPE asset_payment_type")
