"""add_agreement_created_notification

Revision ID: 751a8ca89e25
Revises: 18e290c16ae3
Create Date: 2026-03-10 01:00:06.697739

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '751a8ca89e25'
down_revision = '18e290c16ae3'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Postgres ENUM types cannot be easily updated within a transaction. 
    # Use op.execute to add values one by one.
    
    op.execute("ALTER TYPE notification_type ADD VALUE 'inspection_rejected'")
    op.execute("ALTER TYPE notification_type ADD VALUE 'inspection_complete'")
    op.execute("ALTER TYPE notification_type ADD VALUE 'agreement_created'")
    op.execute("ALTER TYPE notification_type ADD VALUE 'agreement_approved'")
    op.execute("ALTER TYPE notification_type ADD VALUE 'agreement_rejected'")
    op.execute("ALTER TYPE notification_type ADD VALUE 'agreement_update'")


def downgrade() -> None:
    # Downgrading ENUM values in Postgres is non-trivial and often not recommended 
    # as it requires dropping the type or recreating it. 
    pass
