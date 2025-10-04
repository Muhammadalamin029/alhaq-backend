"""allow_notification_user_id_to_reference_both_profiles_and_seller_profiles

Revision ID: 58cdba71a419
Revises: fab7b2c68a8c
Create Date: 2025-10-03 17:17:01.449843

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '58cdba71a419'
down_revision = 'fab7b2c68a8c'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Drop the existing foreign key constraint
    op.drop_constraint('notifications_user_id_fkey', 'notifications', type_='foreignkey')
    
    # Create a function to validate user_id exists in either profiles or seller_profiles
    op.execute("""
        CREATE OR REPLACE FUNCTION validate_notification_user_id()
        RETURNS TRIGGER AS $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM profiles WHERE id = NEW.user_id
                UNION
                SELECT 1 FROM seller_profiles WHERE id = NEW.user_id
            ) THEN
                RAISE EXCEPTION 'user_id % does not exist in profiles or seller_profiles', NEW.user_id;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)
    
    # Create trigger to validate user_id on insert/update
    op.execute("""
        CREATE TRIGGER validate_notification_user_id_trigger
        BEFORE INSERT OR UPDATE ON notifications
        FOR EACH ROW
        EXECUTE FUNCTION validate_notification_user_id();
    """)


def downgrade() -> None:
    # Drop the trigger and function
    op.execute("DROP TRIGGER IF EXISTS validate_notification_user_id_trigger ON notifications;")
    op.execute("DROP FUNCTION IF EXISTS validate_notification_user_id();")
    
    # Recreate the original foreign key constraint to profiles only
    op.create_foreign_key(
        'notifications_user_id_fkey',
        'notifications', 'profiles',
        ['user_id'], ['id']
    )
