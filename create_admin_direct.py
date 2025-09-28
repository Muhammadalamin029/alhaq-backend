#!/usr/bin/env python3
"""
Direct Admin User Creation Script

Quick script to create an admin user with predefined credentials.
Modify the credentials below and run: python create_admin_direct.py
"""

import sys
import os

# Add the project root to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sqlalchemy.orm import Session
from core.auth_service import auth_service
from db.session import SessionLocal
from core.logging_config import get_logger

logger = get_logger("admin_creation")

# 🔧 MODIFY THESE CREDENTIALS
ADMIN_EMAIL = "admin@alhaq.com"
ADMIN_PASSWORD = "AdminPass123!"
ADMIN_BUSINESS_NAME = "Alhaq Administration"
ADMIN_DESCRIPTION = "Platform Administrator"

def create_admin_directly():
    """Create admin user with predefined credentials"""
    print("🔧 Creating admin user...")
    
    db: Session = SessionLocal()
    try:
        # Check if user already exists
        from core.model import User
        existing_user = db.query(User).filter(User.email == ADMIN_EMAIL).first()
        if existing_user:
            print(f"❌ Admin user {ADMIN_EMAIL} already exists!")
            print(f"🆔 Existing User ID: {existing_user.id}")
            print(f"🔑 Role: {existing_user.role}")
            return False
        
        # Create admin user
        user_id = auth_service.create_admin_user(
            db=db,
            email=ADMIN_EMAIL,
            password=ADMIN_PASSWORD,
            business_name=ADMIN_BUSINESS_NAME,
            description=ADMIN_DESCRIPTION
        )
        
        print("✅ Admin user created successfully!")
        print(f"📧 Email: {ADMIN_EMAIL}")
        print(f"🔑 Password: {ADMIN_PASSWORD}")
        print(f"🆔 User ID: {user_id}")
        print(f"👤 Business Name: {ADMIN_BUSINESS_NAME}")
        print(f"🔑 Role: admin")
        
        logger.info(f"Admin user created: {ADMIN_EMAIL} (ID: {user_id})")
        return True
        
    except Exception as e:
        print(f"❌ Failed to create admin user: {str(e)}")
        logger.error(f"Failed to create admin user {ADMIN_EMAIL}: {str(e)}")
        db.rollback()
        return False
    finally:
        db.close()

if __name__ == "__main__":
    print("=" * 60)
    print("🚀 ALHAQ DIRECT ADMIN CREATION")
    print("=" * 60)
    
    try:
        success = create_admin_directly()
        if success:
            print("\n🎉 Admin user creation completed!")
            print("💡 You can now log in to the admin dashboard.")
            print("\n⚠️  SECURITY NOTE: Change the default password after first login!")
        else:
            print("\n💥 Admin user creation failed!")
    except Exception as e:
        print(f"\n💥 Unexpected error: {str(e)}")
        sys.exit(1)
