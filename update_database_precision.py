#!/usr/bin/env python3
"""
Script to update database precision without Alembic
Run this script to increase precision of price/amount fields
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from sqlalchemy import create_engine, text
from db.session import get_db_url
import logging

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def update_database_precision():
    """Update database precision for price/amount fields"""
    
    try:
        # Get database URL from your existing configuration
        database_url = get_db_url()
        engine = create_engine(database_url)
        
        logger.info("Connected to database successfully")
        
        # SQL commands to update precision
        sql_commands = [
            "ALTER TABLE orders ALTER COLUMN total_amount TYPE NUMERIC(15,2);",
            "ALTER TABLE order_items ALTER COLUMN price TYPE NUMERIC(15,2);", 
            "ALTER TABLE products ALTER COLUMN price TYPE NUMERIC(15,2);"
        ]
        
        # Execute commands in a transaction
        with engine.begin() as conn:
            logger.info("Starting database precision update...")
            
            for i, sql in enumerate(sql_commands, 1):
                logger.info(f"Executing command {i}/3: {sql}")
                conn.execute(text(sql))
                logger.info(f"✅ Command {i} completed successfully")
            
            logger.info("All precision updates completed successfully!")
        
        # Verify the changes
        verify_sql = """
        SELECT 
            table_name,
            column_name,
            data_type,
            numeric_precision,
            numeric_scale
        FROM information_schema.columns 
        WHERE table_name IN ('orders', 'order_items', 'products') 
          AND column_name IN ('total_amount', 'price')
        ORDER BY table_name, column_name;
        """
        
        with engine.connect() as conn:
            result = conn.execute(text(verify_sql))
            logger.info("\n📊 Updated column information:")
            logger.info("Table Name | Column Name | Data Type | Precision | Scale")
            logger.info("-" * 60)
            
            for row in result:
                logger.info(f"{row.table_name:12} | {row.column_name:11} | {row.data_type:9} | {row.numeric_precision:9} | {row.numeric_scale:5}")
        
        logger.info("\n🎉 Database precision update completed successfully!")
        logger.info("The numeric field overflow error should now be resolved.")
        
    except Exception as e:
        logger.error(f"❌ Error updating database precision: {str(e)}")
        logger.error("Please check your database connection and try again.")
        sys.exit(1)

if __name__ == "__main__":
    update_database_precision()
