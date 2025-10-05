"""fix_notification_preferences_user_id_fk

Revision ID: 7f1c5a2584f8
Revises: 58cdba71a419
Create Date: 2025-10-04 15:53:06.168380

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '7f1c5a2584f8'
down_revision = '58cdba71a419'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Drop the existing foreign key constraint on notification_preferences.user_id
    op.drop_constraint('notification_preferences_user_id_fkey', 'notification_preferences', type_='foreignkey')
    
    # Create a function to validate user_id exists in either profiles or seller_profiles
    op.execute("""
        CREATE OR REPLACE FUNCTION validate_notification_preferences_user_id()
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
        CREATE TRIGGER validate_notification_preferences_user_id_trigger
        BEFORE INSERT OR UPDATE ON notification_preferences
        FOR EACH ROW
        EXECUTE FUNCTION validate_notification_preferences_user_id();
    """)


def downgrade() -> None:
    # Drop the trigger and function
    op.execute("DROP TRIGGER IF EXISTS validate_notification_preferences_user_id_trigger ON notification_preferences")
    op.execute("DROP FUNCTION IF EXISTS validate_notification_preferences_user_id()")
    
    # Recreate the original foreign key constraint
    op.create_foreign_key('notification_preferences_user_id_fkey', 'notification_preferences', 'profiles', ['user_id'], ['id'])
