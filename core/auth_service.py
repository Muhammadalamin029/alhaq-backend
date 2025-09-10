from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from sqlalchemy import func
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, Tuple
from fastapi import HTTPException, status

from core.model import User, Profile, SellerProfile
from core.auth import hashpassword, verify_password
from core.password_policy import PasswordPolicy, validate_password_change
from schemas.auth import UserRole, UserProfileResponse, CustomerProfileResponse, SellerProfileResponse


class AuthService:
    """Service class for authentication operations"""
    
    def create_user(self, db: Session, email: str, password: str, role: UserRole, full_name: str, bio: str) -> str:
        """
        Create a new user with appropriate profile
        
        Returns user ID
        """
        # Prevent admin creation via public endpoint
        if role == UserRole.ADMIN:
            raise HTTPException(status_code=403, detail="Cannot register as admin")
        
        # Validate password policy
        PasswordPolicy.validate_password(password)

        hashed_password = hashpassword(password)
        user = User(
            email=email, 
            hashed_password=hashed_password, 
            role=role.value,
            password_changed_at=func.current_timestamp()
        )
        db.add(user)
        db.flush()  # ensures user.id exists

        # Assign correct profile - Admin uses seller profile structure
        if role == UserRole.SELLER or role == UserRole.ADMIN:
            profile = SellerProfile(
                id=user.id, business_name=full_name, description=bio)
        else:  # customer
            profile = Profile(id=user.id, name=full_name, bio=bio)

        db.add(profile)
        db.commit()
        db.refresh(user)
        return str(user.id)
    
    def authenticate_user(self, db: Session, email: str, password: str) -> Tuple[User, bool]:
        """
        Authenticate user and handle login attempts
        
        Returns (User, is_locked) tuple
        Raises HTTPException on authentication failure
        """
        user = db.query(User).filter(User.email == email).first()
        
        # Check if user exists
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, 
                detail="Invalid credentials"
            )
        
        # Check if account is locked
        if user.locked_until and user.locked_until > datetime.utcnow():
            remaining_time = (user.locked_until - datetime.utcnow()).total_seconds() / 60
            raise HTTPException(
                status_code=status.HTTP_423_LOCKED,
                detail=f"Account is locked. Try again in {int(remaining_time)} minutes."
            )
        
        # Verify password
        if not verify_password(password, user.hashed_password):
            # Increment failed login attempts
            user.failed_login_attempts += 1
            
            # Lock account after 5 failed attempts
            if user.failed_login_attempts >= 5:
                user.locked_until = datetime.utcnow() + timedelta(minutes=15)
                db.commit()
                raise HTTPException(
                    status_code=status.HTTP_423_LOCKED,
                    detail="Account locked due to multiple failed login attempts. Try again in 15 minutes."
                )
            
            db.commit()
            remaining_attempts = 5 - user.failed_login_attempts
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, 
                detail=f"Invalid credentials. {remaining_attempts} attempts remaining before account lock."
            )
        
        # Reset failed attempts on successful login
        user.failed_login_attempts = 0
        user.locked_until = None
        user.last_login = datetime.utcnow()
        db.commit()
        
        return user, False
    
    def get_user_profile(self, db: Session, user_id: str) -> Dict[str, Any]:
        """
        Get complete user profile with role-specific data
        """
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )
        
        # Get user profile based on role
        profile = None
        if user.role == "customer":
            profile_data = db.query(Profile).filter(Profile.id == user.id).first()
            if profile_data:
                profile = CustomerProfileResponse.model_validate(profile_data)
        elif user.role in ["seller", "admin"]:  # Both seller and admin use seller profile
            profile_data = db.query(SellerProfile).filter(SellerProfile.id == user.id).first()
            if profile_data:
                profile = SellerProfileResponse.model_validate(profile_data)
        
        user_response = UserProfileResponse.model_validate(user)
        
        return {
            "user": user_response,
            "profile": profile
        }
    
    def update_user_profile(self, db: Session, user_id: str, update_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Update user profile with validation
        """
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )
        
        if not update_data:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No fields provided for update"
            )
        
        # Update user fields if provided
        if "email" in update_data:
            # Check if email already exists
            existing_user = db.query(User).filter(
                User.email == update_data["email"],
                User.id != user.id
            ).first()
            if existing_user:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Email already registered by another user"
                )
            user.email = update_data["email"]
            # Reset email verification when email changes
            user.email_verified = False
            user.email_verified_at = None
        
        # Update profile fields based on user role
        if user.role == "customer":
            profile = db.query(Profile).filter(Profile.id == user.id).first()
            if profile:
                if "full_name" in update_data:
                    profile.name = update_data["full_name"]
                if "bio" in update_data:
                    profile.bio = update_data["bio"]
        
        elif user.role in ["seller", "admin"]:  # Both use seller profile structure
            profile = db.query(SellerProfile).filter(SellerProfile.id == user.id).first()
            if profile:
                if "full_name" in update_data:
                    profile.business_name = update_data["full_name"]
                if "bio" in update_data:
                    profile.description = update_data["bio"]
        
        user.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(user)
        
        return self.get_user_profile(db, user_id)
    
    def change_user_password(self, db: Session, user_id: str, current_password: str, new_password: str) -> Dict[str, Any]:
        """
        Change user password with validation
        """
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )
        
        # Verify current password
        if not verify_password(current_password, user.hashed_password):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Current password is incorrect"
            )
        
        # Validate new password with additional checks
        validate_password_change(
            current_password=current_password,
            new_password=new_password,
            user_email=user.email
        )
        
        # Update password
        user.hashed_password = hashpassword(new_password)
        user.password_changed_at = datetime.utcnow()
        # Reset failed login attempts when password is changed
        user.failed_login_attempts = 0
        user.locked_until = None
        
        db.commit()
        
        return {
            "password_changed_at": user.password_changed_at.isoformat()
        }
    
    def create_admin_user(self, db: Session, email: str, password: str, business_name: str, description: str = None) -> str:
        """
        Create admin user - only callable internally or by existing admins
        Admin users use seller profile structure
        """
        # Validate password policy
        PasswordPolicy.validate_password(password)

        hashed_password = hashpassword(password)
        user = User(
            email=email, 
            hashed_password=hashed_password, 
            role="admin",
            password_changed_at=func.current_timestamp()
        )
        db.add(user)
        db.flush()

        # Admin uses seller profile structure
        profile = SellerProfile(
            id=user.id, 
            business_name=business_name, 
            description=description or "System Administrator"
        )
        
        db.add(profile)
        db.commit()
        db.refresh(user)
        return str(user.id)
    
    def get_user_by_email(self, db: Session, email: str) -> Optional[User]:
        """Get user by email"""
        return db.query(User).filter(User.email == email).first()
    
    def get_user_by_id(self, db: Session, user_id: str) -> Optional[User]:
        """Get user by ID"""
        return db.query(User).filter(User.id == user_id).first()
    
    def is_account_locked(self, user: User) -> bool:
        """Check if user account is locked"""
        if not user.locked_until:
            return False
        return user.locked_until > datetime.utcnow()
    
    def unlock_user_account(self, db: Session, user_id: str) -> bool:
        """Manually unlock user account (admin function)"""
        user = self.get_user_by_id(db, user_id)
        if not user:
            return False
        
        user.failed_login_attempts = 0
        user.locked_until = None
        db.commit()
        return True
    
    def reset_user_password_attempts(self, db: Session, user_id: str) -> bool:
        """Reset failed login attempts (admin function)"""
        user = self.get_user_by_id(db, user_id)
        if not user:
            return False
        
        user.failed_login_attempts = 0
        db.commit()
        return True


# Create service instance
auth_service = AuthService()
