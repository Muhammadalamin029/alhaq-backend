"""add_payment_plan_settings

Revision ID: ac430d82987d
Revises: 958d59a6317e
Create Date: 2026-09-10 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'ac430d82987d'
down_revision = '958d59a6317e'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Per-listing "monthly allowed" toggle - defaults to True so existing
    # listings keep behaving exactly as they do today.
    op.add_column('cars', sa.Column('monthly_allowed', sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column('properties', sa.Column('monthly_allowed', sa.Boolean(), nullable=False, server_default=sa.true()))

    # 2. Global installment eligibility settings - default 0 means "no
    # restriction", matching current unrestricted behavior.
    op.add_column('system_settings', sa.Column('installment_min_percent', sa.Numeric(5, 2), nullable=False, server_default='0'))
    op.add_column('system_settings', sa.Column('installment_price_floor', sa.Numeric(15, 2), nullable=False, server_default='0'))

    # 3. Explicit 3-way payment_plan on agreements, backfilled from the
    # existing plan_type + payment history so it can be made NOT NULL safely.
    agreement_payment_plan = sa.Enum('monthly', 'full_payment', 'installment', name='agreement_payment_plan')
    agreement_payment_plan.create(op.get_bind(), checkfirst=True)
    op.add_column('general_agreements', sa.Column('payment_plan', agreement_payment_plan, nullable=True))

    op.execute("""
        UPDATE general_agreements
        SET payment_plan = 'monthly'
        WHERE plan_type = 'structured'
    """)
    op.execute("""
        UPDATE general_agreements
        SET payment_plan = 'full_payment'
        WHERE plan_type = 'flexible'
          AND EXISTS (
              SELECT 1 FROM payments
              WHERE payments.agreement_id = general_agreements.id
                AND payments.payment_type = 'full_pay'
          )
    """)
    op.execute("""
        UPDATE general_agreements
        SET payment_plan = 'installment'
        WHERE plan_type = 'flexible'
          AND payment_plan IS NULL
    """)

    op.alter_column('general_agreements', 'payment_plan', nullable=False)


def downgrade() -> None:
    op.drop_column('general_agreements', 'payment_plan')
    sa.Enum(name='agreement_payment_plan').drop(op.get_bind(), checkfirst=True)

    op.drop_column('system_settings', 'installment_price_floor')
    op.drop_column('system_settings', 'installment_min_percent')

    op.drop_column('properties', 'monthly_allowed')
    op.drop_column('cars', 'monthly_allowed')
