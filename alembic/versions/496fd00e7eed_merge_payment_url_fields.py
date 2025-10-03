"""merge payment url fields

Revision ID: 496fd00e7eed
Revises: 98a88565cc4f, add_payment_url_fields
Create Date: 2025-10-03 15:01:40.030424

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '496fd00e7eed'
down_revision = ('98a88565cc4f', 'add_payment_url_fields')
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
