#!/usr/bin/env python3
"""
Admin User Creation Script

This script creates an admin user for the Alhaq platform.
Usage: python create_admin.py
"""

import sys
import os
from getpass import getpass

# Add the project root to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sqlalchemy.orm import Session
from core.auth_service import auth_service
from db.session import SessionLocal
from core.logging_config import get_logger

logger = get_logger("admin_creation")

def create_admin_user():
    """Interactive admin user creation"""
    print("=" * 50)
    print("🔧 ALHAQ ADMIN USER CREATION")
    print("=" * 50)
    
    # Get admin details
    email = input("Enter admin email: ").strip()
    if not email:
        print("❌ Email is required!")
        return False
    
    # Validate email format
    import re
    email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    if not re.match(email_pattern, email):
        print("❌ Invalid email format!")
        return False
    
    business_name = input("Enter admin/business name (default: 'System Administrator'): ").strip()
    if not business_name:
        business_name = "System Administrator"
    
    description = input("Enter description (optional): ").strip()
    
    # Get password securely
    print("\n🔒 Password Requirements:")
    print("- At least 8 characters")
    print("- Must contain uppercase, lowercase, number, and special character")
    
    password = getpass("Enter admin password: ")
    if not password:
        print("❌ Password is required!")
        return False
    
    password_confirm = getpass("Confirm admin password: ")
    if password != password_confirm:
        print("❌ Passwords do not match!")
        return False
    
    # Create admin user
    db: Session = SessionLocal()
    try:
        print(f"\n🚀 Creating admin user: {email}")
        
        # Check if user already exists
        from core.model import User
        existing_user = db.query(User).filter(User.email == email).first()
        if existing_user:
            print(f"❌ User with email {email} already exists!")
            return False
        
        # Create admin user
        user_id = auth_service.create_admin_user(
            db=db,
            email=email,
            password=password,
            business_name=business_name,
            description=description
        )
        
        print(f"✅ Admin user created successfully!")
        print(f"📧 Email: {email}")
        print(f"🆔 User ID: {user_id}")
        print(f"👤 Business Name: {business_name}")
        print(f"🔑 Role: admin")
        
        logger.info(f"Admin user created: {email} (ID: {user_id})")
        return True
        
    except Exception as e:
        print(f"❌ Failed to create admin user: {str(e)}")
        logger.error(f"Failed to create admin user {email}: {str(e)}")
        db.rollback()
        return False
    finally:
        db.close()

def main():
    """Main function"""
    try:
        success = create_admin_user()
        if success:
            print("\n🎉 Admin user creation completed successfully!")
            print("💡 You can now log in to the admin dashboard with these credentials.")
        else:
            print("\n💥 Admin user creation failed!")
            sys.exit(1)
    except KeyboardInterrupt:
        print("\n\n⚠️  Operation cancelled by user.")
        sys.exit(1)
    except Exception as e:
        print(f"\n💥 Unexpected error: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main()
