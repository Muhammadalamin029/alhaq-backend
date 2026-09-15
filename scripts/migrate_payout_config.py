#!/usr/bin/env python3
"""
Migration script for payout account configuration
Works for both development and production environments
"""

import os
import sys
import asyncio
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

def get_database_url():
    """Get database URL from environment variables"""
    # Try production first, then development
    prod_url = os.getenv('DATABASE_URL')
    dev_url = os.getenv('LOCAL_DATABASE_URL')
    
    if prod_url:
        print("Using production database URL")
        return prod_url
    elif dev_url:
        print("Using development database URL")
        return dev_url
    else:
        print("No database URL found in environment variables")
        sys.exit(1)

def run_migration():
    """Run the payout account configuration migration"""
    database_url = get_database_url()
    
    # Create engine
    engine = create_engine(database_url)
    
    try:
        with engine.connect() as connection:
            # Start transaction
            trans = connection.begin()
            
            try:
                print("Starting payout account configuration migration...")
                
                # Check if payout_account_configured column exists
                result = connection.execute(text("""
                    SELECT column_name 
                    FROM information_schema.columns 
                    WHERE table_name = 'seller_profiles' 
                    AND column_name = 'payout_account_configured'
                """))
                
                if not result.fetchone():
                    print("Adding payout_account_configured column...")
                    connection.execute(text("""
                        ALTER TABLE seller_profiles 
                        ADD COLUMN payout_account_configured BOOLEAN DEFAULT FALSE
                    """))
                else:
                    print("payout_account_configured column already exists")
                
                # Update existing records to set payout_account_configured based on existing data
                print("Updating payout_account_configured status...")
                connection.execute(text("""
                    UPDATE seller_profiles 
                    SET payout_account_configured = (
                        payout_account_number IS NOT NULL 
                        AND payout_bank_code IS NOT NULL 
                        AND payout_recipient_code IS NOT NULL
                    )
                """))
                
                # Commit transaction
                trans.commit()
                print("Migration completed successfully!")
                
            except Exception as e:
                print(f"Error during migration: {e}")
                trans.rollback()
                raise
                
    except Exception as e:
        print(f"Database connection error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    run_migration()
