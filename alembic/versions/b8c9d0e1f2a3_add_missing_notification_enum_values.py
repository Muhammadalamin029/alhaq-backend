"""add missing notification enum values (agreement_activated, payment_refunded)

Revision ID: b8c9d0e1f2a3
Revises: m3r6eh3a4d5f
Create Date: 2026-09-25 00:00:00.000000

These types were already referenced in code (payment_service agreement
activation flow, refund flow, email templates) but were never added to the
Postgres `notification_type` enum, causing:

  psycopg2.errors.InvalidTextRepresentation: invalid input value for enum
  notification_type: "agreement_activated"

which 500'd POST /payments/verify AFTER the user had already paid.
"""
from alembic import op


# revision identifiers, used by Alembic.
revision = 'b8c9d0e1f2a3'
down_revision = 'm3r6eh3a4d5f'
branch_labels = None
depends_on = None


_NEW_VALUES = ('agreement_activated', 'payment_refunded')


def upgrade() -> None:
    # Idempotent: only add values that are not already present.
    # (Plain `ALTER TYPE ... ADD VALUE` fails if the value exists, and
    #  cannot run inside a transaction block on some PG versions when
    #  combined — the DO block keeps `alembic upgrade heads` safe to
    #  re-run across environments at different revisions.)
    for value in _NEW_VALUES:
        op.execute(
            f"""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_enum e
                    JOIN pg_type t ON t.oid = e.enumtypid
                    WHERE t.typname = 'notification_type'
                      AND e.enumlabel = '{value}'
                ) THEN
                    EXECUTE 'ALTER TYPE notification_type ADD VALUE ''{value}''';
                END IF;
            END
            $$;
            """
        )


def downgrade() -> None:
    # Postgres cannot remove single enum values without recreating the type.
    pass
