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
            raise HTTPException(
                status_code=403, detail="Cannot register as admin")

        # Validate password policy
        PasswordPolicy.validate_password(password)

        hashed_password = hashpassword(password)
        user = User(
            email=email,
            hashed_password=hashed_password,
            role=role,
            password_changed_at=func.current_timestamp()
        )
        db.add(user)
        db.flush()  # ensures user.id exists

        # Assign correct profile - Admin uses seller profile structure
        if role == UserRole.SELLER or role == UserRole.ADMIN:
            profile = SellerProfile(
                id=user.id, 
                business_name=full_name, 
                description=bio,
                contact_email=email,  # Use user email as contact email
                kyc_status="approved" if role == UserRole.ADMIN else "pending",
                approval_date=func.current_date() if role == UserRole.ADMIN else None
            )
        else:  # customer
            profile = Profile(id=user.id, name=full_name, bio=bio)

        db.add(profile)
        db.commit()
        db.refresh(user)
        return str(user.id)

    def create_seller(self, db: Session, email: str, password: str, business_name: str, 
                     contact_email: str, contact_phone: str, description: str, 
                     website_url: str = None) -> str:
        """
        Create a new seller with seller-specific profile data
        
        Returns user ID
        """
        # Validate password policy
        PasswordPolicy.validate_password(password)

        hashed_password = hashpassword(password)
        user = User(
            email=email,
            hashed_password=hashed_password,
            role=UserRole.SELLER,
            password_changed_at=func.current_timestamp()
        )
        db.add(user)
        db.flush()  # ensures user.id exists

        # Create seller profile with proper seller data
        seller_profile = SellerProfile(
            id=user.id,
            business_name=business_name,
            description=description,
            contact_email=contact_email,
            contact_phone=contact_phone,
            website_url=website_url,
            kyc_status="pending"  # New sellers start with pending KYC
        )

        db.add(seller_profile)
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
            remaining_time = (user.locked_until -
                              datetime.utcnow()).total_seconds() / 60
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
            profile_data = db.query(Profile).filter(
                Profile.id == user.id).first()
            if profile_data:
                profile = CustomerProfileResponse.model_validate(profile_data)
        # Both seller and admin use seller profile
        elif user.role in ["seller", "admin"]:
            profile_data = db.query(SellerProfile).filter(
                SellerProfile.id == user.id).first()
            if profile_data:
                profile = SellerProfileResponse.model_validate(profile_data)

        user_response = UserProfileResponse.model_validate(user)

        return {
            "user": user_response,
            "profile": profile
        }

    def update_user_profile(self, db: Session, user_id: str, update_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Update user profile with validation, aligned with frontend formData structure
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

        # Update email if provided
        if "email" in update_data:
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
            user.email_verified = False
            user.email_verified_at = None

        # Update profile based on role
        if user.role == "customer":
            profile = db.query(Profile).filter(Profile.id == user.id).first()
            if profile:
                # Full name = firstName + lastName
                if "firstName" in update_data or "lastName" in update_data:
                    first_name = update_data.get("firstName", "").strip()
                    last_name = update_data.get("lastName", "").strip()
                    profile.name = f"{first_name} {last_name}".strip()
                if "bio" in update_data:
                    profile.bio = update_data["bio"]
                if "avatar_url" in update_data:
                    profile.avatar_url = update_data["avatar_url"]

        elif user.role in ["seller", "admin"]:  # Seller/Admin share same structure
            profile = db.query(SellerProfile).filter(
                SellerProfile.id == user.id).first()
            if profile:
                if "business_name" in update_data:
                    profile.business_name = update_data["business_name"]
                if "description" in update_data:
                    profile.description = update_data["description"]
                if "contact_email" in update_data:
                    profile.contact_email = update_data["contact_email"]
                if "contact_phone" in update_data:
                    profile.contact_phone = update_data["contact_phone"]
                if "website_url" in update_data:
                    profile.website_url = update_data["website_url"]
                if "logo_url" in update_data:
                    profile.logo_url = update_data["logo_url"]

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
            description=description or "System Administrator",
            contact_email=email,  # Use admin email as contact email
            contact_phone=None,   # Optional for admin
            website_url=None,     # Optional for admin
            kyc_status="approved", # Admins are auto-approved
            approval_date=func.current_date()  # Set approval date to today
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

    # ---------------- EMAIL VERIFICATION METHODS ---------------- #

    def send_verification_email(self, db: Session, email: str) -> Dict[str, Any]:
        """
        Send verification email to user

        Args:
            db: Database session
            email: User's email address

        Returns:
            dict: Response with success status and message
        """
        from core.redis_client import verification_manager
        from core.tasks import send_verification_email

        # Check if user exists
        user = self.get_user_by_email(db, email)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )

        # Check if user is already verified
        if user.email_verified:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email is already verified"
            )

        # Check rate limiting
        if verification_manager.is_rate_limited(email):
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many verification requests. Please try again later."
            )

        # Get user name based on profile type
        user_name = "User"  # Default fallback
        if user.role == "customer":
            profile = db.query(Profile).filter(Profile.id == user.id).first()
            if profile:
                user_name = profile.name
        elif user.role in ["seller", "admin"]:
            profile = db.query(SellerProfile).filter(
                SellerProfile.id == user.id).first()
            if profile:
                user_name = profile.business_name

        # Increment rate limit counter
        verification_manager.increment_rate_limit(email)

        # Send verification email asynchronously
        task = send_verification_email.delay(email, user_name)

        return {
            "message": f"Verification email sent to {email}",
            "task_id": task.id,
            "expires_in_minutes": 15  # verification_manager.EMAIL_VERIFICATION_EXPIRE_MINUTES
        }

    def verify_email(self, db: Session, email: str, verification_code: str) -> Dict[str, Any]:
        """
        Verify user's email with verification code

        Args:
            db: Database session
            email: User's email address
            verification_code: 6-digit verification code

        Returns:
            dict: Response with success status and message
        """
        from core.redis_client import verification_manager
        from core.tasks import send_welcome_email

        # Check if user exists
        user = self.get_user_by_email(db, email)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )

        # Check if user is already verified
        if user.email_verified:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email is already verified"
            )

        # Verify the code
        if not verification_manager.verify_code(email, verification_code, "verification"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid or expired verification code"
            )

        # Update user verification status
        user.email_verified = True
        user.email_verified_at = datetime.utcnow()
        db.commit()

        # Get user name for welcome email
        user_name = "User"  # Default fallback
        if user.role == "customer":
            profile = db.query(Profile).filter(Profile.id == user.id).first()
            if profile:
                user_name = profile.name
        elif user.role in ["seller", "admin"]:
            profile = db.query(SellerProfile).filter(
                SellerProfile.id == user.id).first()
            if profile:
                user_name = profile.business_name

        # Send welcome email (async, non-blocking)
        send_welcome_email.delay(email, user_name)

        return {
            "message": "Email verified successfully",
            "verified_at": user.email_verified_at.isoformat()
        }

    def request_password_reset(self, db: Session, email: str) -> Dict[str, Any]:
        """
        Send password reset email to user

        Args:
            db: Database session
            email: User's email address

        Returns:
            dict: Response with success status and message
        """
        from core.redis_client import verification_manager
        from core.tasks import send_password_reset_email

        # Check if user exists (but don't reveal if email doesn't exist for security)
        user = self.get_user_by_email(db, email)

        # Always return success to prevent email enumeration attacks
        # But only send email if user actually exists
        if user:
            # Check rate limiting
            if verification_manager.is_rate_limited(email, max_attempts=3, window_minutes=60):
                # Still return success but log the attempt
                pass
            else:
                # Get user name based on profile type
                user_name = "User"  # Default fallback
                if user.role == "customer":
                    profile = db.query(Profile).filter(
                        Profile.id == user.id).first()
                    if profile:
                        user_name = profile.name
                elif user.role in ["seller", "admin"]:
                    profile = db.query(SellerProfile).filter(
                        SellerProfile.id == user.id).first()
                    if profile:
                        user_name = profile.business_name

                # Increment rate limit counter
                verification_manager.increment_rate_limit(
                    email, window_minutes=60)

                # Send password reset email asynchronously
                send_password_reset_email.delay(email, user_name)

        return {
            "message": f"If an account with {email} exists, a password reset email has been sent",
            "expires_in_minutes": 30  # verification_manager.PASSWORD_RESET_EXPIRE_MINUTES
        }

    def reset_password_with_code(self, db: Session, email: str, reset_code: str, new_password: str) -> Dict[str, Any]:
        """
        Reset user password using verification code

        Args:
            db: Database session
            email: User's email address
            reset_code: 6-digit reset code
            new_password: New password

        Returns:
            dict: Response with success status and message
        """
        from core.redis_client import verification_manager

        # Check if user exists
        user = self.get_user_by_email(db, email)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )

        # Verify the reset code
        if not verification_manager.verify_code(email, reset_code, "password_reset"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid or expired reset code"
            )

        # Validate new password
        PasswordPolicy.validate_password(new_password)

        # Update password
        user.hashed_password = hashpassword(new_password)
        user.password_changed_at = datetime.utcnow()
        # Reset failed login attempts and unlock account
        user.failed_login_attempts = 0
        user.locked_until = None

        db.commit()

        return {
            "message": "Password reset successfully",
            "password_changed_at": user.password_changed_at.isoformat()
        }

    def get_verification_status(self, db: Session, email: str) -> Dict[str, Any]:
        """
        Get email verification status for user

        Args:
            db: Database session
            email: User's email address

        Returns:
            dict: Verification status information
        """
        from core.redis_client import verification_manager

        user = self.get_user_by_email(db, email)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )

        # Check if there's a pending verification code
        remaining_time = verification_manager.get_remaining_time(
            email, "verification")

        return {
            "email_verified": user.email_verified,
            "verified_at": user.email_verified_at.isoformat() if user.email_verified_at else None,
            "has_pending_verification": remaining_time > 0,
            "verification_expires_in_seconds": remaining_time if remaining_time > 0 else None,
            "can_resend_verification": not verification_manager.is_rate_limited(email)
        }


# Create service instance
auth_service = AuthService()
