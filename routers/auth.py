from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm, OAuth2PasswordBearer
from sqlalchemy.orm import Session
from datetime import timedelta
from pydantic import BaseModel

from core.config import settings
from core.auth import create_access_token, create_refresh_token, decode_token, get_current_user
from core.auth_service import auth_service
from core.password_policy import PasswordPolicy, PASSWORD_REQUIREMENTS
from db.session import get_db
from schemas.auth import (
    LoginRequest, RegisterRequest, SellerRegisterRequest, TokenResponse, RefreshRequest,
    ChangePasswordRequest, UpdateProfileRequest, FullUserProfileResponse,
    VerifyEmailRequest, ResendVerificationRequest, VerifyPasswordResetRequest,
    EmailVerificationResponse, PasswordResetResponse, LoginRequest, SendVerificationRequest, RequestPasswordResetRequest
)
from sqlalchemy.exc import IntegrityError
from core.logging_config import get_logger, log_auth_event, log_error
# Get logger for auth routes
auth_logger = get_logger("auth")

router = APIRouter()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


def generate_tokens(user_id: str, role: str):
    """Generate access and refresh tokens for user"""
    user_data = {"sub": user_id, "role": role}
    access_token = create_access_token(user_data, timedelta(
        minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES))
    refresh_token = create_refresh_token(
        user_data, timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS))
    return access_token, refresh_token


# ---------------- AUTHENTICATION ---------------- #

@router.post("/refresh", response_model=TokenResponse)
def refresh_tokens(refresh_request: RefreshRequest):
    """Refresh access token using refresh token"""
    try:
        payload = decode_token(
            refresh_request.refresh_token, settings.REFRESH_SECRET_KEY)
    except HTTPException:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token"
        )

    user_id, role = payload.get("sub"), payload.get("role")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token data")

    access_token, refresh_token = generate_tokens(user_id, role)
    return TokenResponse(access_token=access_token, refresh_token=refresh_token)


@router.post("/login", response_model=TokenResponse)
def login(form_data: LoginRequest, db: Session = Depends(get_db)):
    """Authenticate user and return tokens"""
    try:
        auth_logger.info(f"Login attempt for user: {form_data.email}")
        
        user, _ = auth_service.authenticate_user(
            db, form_data.email, form_data.password)
        
        # Log successful login
        log_auth_event(
            auth_logger, 
            "user_login", 
            email=form_data.email,
            user_id=str(user.id),
            success=True,
            user_role=user.role
        )
        
        access_token, refresh_token = generate_tokens(str(user.id), user.role)
        return TokenResponse(access_token=access_token, refresh_token=refresh_token)
        
    except HTTPException as e:
        # Log failed login attempt
        log_auth_event(
            auth_logger,
            "user_login_failed",
            email=form_data.email,
            success=False,
            reason=str(e.detail),
            status_code=e.status_code
        )
        raise
    except Exception as e:
        log_error(auth_logger, f"Unexpected error during login for {form_data.email}", e, email=form_data.email)
        raise HTTPException(status_code=500, detail="Login failed")


# ---------------- REGISTRATION ---------------- #

@router.post("/register/customer", response_model=TokenResponse, status_code=201)
def register_customer(body: RegisterRequest, db: Session = Depends(get_db)):
    """Register a new customer and return authentication tokens"""
    try:
        auth_logger.info(f"Customer registration attempt: {body.email}")
        
        user_id = auth_service.create_user(
            db, body.email, body.password, "customer", body.full_name, body.bio
        )
        
        # Log successful registration
        log_auth_event(
            auth_logger,
            "customer_registration",
            email=body.email,
            user_id=user_id,
            success=True,
            user_role="customer"
        )
        
        # Generate tokens for immediate login after registration
        access_token, refresh_token = generate_tokens(user_id, "customer")
        return TokenResponse(access_token=access_token, refresh_token=refresh_token)
        
    except IntegrityError as e:
        db.rollback()
        log_auth_event(
            auth_logger,
            "customer_registration_failed",
            email=body.email,
            success=False,
            reason="Email already registered"
        )
        raise HTTPException(status_code=400, detail="Email already registered")
    except HTTPException as e:
        log_auth_event(
            auth_logger,
            "customer_registration_failed", 
            email=body.email,
            success=False,
            reason=str(e.detail)
        )
        raise
    except Exception as e:
        db.rollback()
        log_error(auth_logger, f"Customer registration failed for {body.email}", e, email=body.email)
        raise HTTPException(status_code=500, detail="Registration failed")


@router.post("/register/seller", response_model=TokenResponse, status_code=201)
def register_seller(body: SellerRegisterRequest, db: Session = Depends(get_db)):
    """Register a new seller and return authentication tokens"""

    try:
        auth_logger.info(f"Seller registration attempt: {body.email}")
        
        user_id = auth_service.create_seller(
            db, 
            email=body.email, 
            password=body.password, 
            business_name=body.business_name,
            contact_email=body.contact_email,
            contact_phone=body.contact_phone,
            description=body.description,
            website_url=body.website_url
        )
        
        # Send verification email
        try:
            auth_service.send_verification_email(db, body.email)
            auth_logger.info(f"Verification email sent to seller: {body.email}")
        except Exception as e:
            auth_logger.warning(f"Failed to send verification email to {body.email}: {str(e)}")
            # Don't fail registration if email sending fails
        
        # Log successful registration
        log_auth_event(
            auth_logger,
            "seller_registration",
            email=body.email,
            user_id=user_id,
            success=True,
            user_role="seller"
        )
        
        # Generate tokens for immediate login after registration
        access_token, refresh_token = generate_tokens(user_id, "seller")
        return TokenResponse(access_token=access_token, refresh_token=refresh_token)
        
    except IntegrityError as e:
        db.rollback()
        log_auth_event(
            auth_logger,
            "seller_registration_failed",
            email=body.email,
            success=False,
            reason="Email already registered"
        )
        raise HTTPException(status_code=400, detail="Email already registered")
    except HTTPException as e:
        log_auth_event(
            auth_logger,
            "seller_registration_failed", 
            email=body.email,
            success=False,
            reason=str(e.detail)
        )
        raise
    except Exception as e:
        db.rollback()
        log_error(auth_logger, f"Seller registration failed for {body.email}", e, email=body.email)
        raise HTTPException(status_code=500, detail="Registration failed")


# ---------------- PROFILE MANAGEMENT ---------------- #

@router.get("/me", response_model=FullUserProfileResponse)
def get_current_user_profile(
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get current authenticated user's profile"""
    try:
        auth_logger.debug(f"Profile fetch request for user: {current_user['id']}")
        
        profile_data = auth_service.get_user_profile(db, current_user["id"])
        
        auth_logger.info(f"Profile fetched successfully for user: {current_user['id']}")
        return FullUserProfileResponse(**profile_data)
        
    except HTTPException:
        raise
    except Exception as e:
        log_error(auth_logger, f"Failed to fetch profile for user {current_user['id']}", e, user_id=current_user['id'])
        raise HTTPException(status_code=500, detail="Failed to fetch profile")


@router.put("/me", response_model=FullUserProfileResponse)
def update_current_user_profile(
    payload: UpdateProfileRequest,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update current authenticated user's profile"""
    try:
        update_data = payload.model_dump(exclude_unset=True)
        
        auth_logger.info(f"Profile update request for user: {current_user['id']}", extra={
            "user_id": current_user['id'],
            "update_fields": list(update_data.keys())
        })

        print(update_data)
        
        profile_data = auth_service.update_user_profile(
            db, current_user["id"], update_data)
        
        auth_logger.info(f"Profile updated successfully for user: {current_user['id']}")
        return FullUserProfileResponse(**profile_data)
        
    except HTTPException:
        raise
    except Exception as e:
        log_error(auth_logger, f"Failed to update profile for user {current_user['id']}", e, 
                  user_id=current_user['id'], update_fields=list(update_data.keys()) if 'update_data' in locals() else [])
        raise HTTPException(status_code=500, detail="Failed to update profile")


@router.put("/change-password", status_code=status.HTTP_200_OK)
def change_password(
    payload: ChangePasswordRequest,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Change user's password"""
    try:
        auth_logger.info(f"Password change request for user: {current_user['id']}")
        
        password_data = auth_service.change_user_password(
            db, current_user["id"], payload.current_password, payload.new_password
        )
        
        # Log successful password change
        log_auth_event(
            auth_logger,
            "password_change",
            user_id=current_user['id'],
            success=True
        )
        
        return {
            "success": True,
            "message": "Password changed successfully",
            "data": password_data
        }
        
    except HTTPException as e:
        # Log failed password change
        log_auth_event(
            auth_logger,
            "password_change_failed",
            user_id=current_user['id'],
            success=False,
            reason=str(e.detail)
        )
        raise
    except Exception as e:
        log_error(auth_logger, f"Password change failed for user {current_user['id']}", e, user_id=current_user['id'])
        raise HTTPException(status_code=500, detail="Password change failed")


# ---------------- PASSWORD POLICY ---------------- #

class PasswordStrengthRequest(BaseModel):
    password: str


@router.get("/password-policy")
def get_password_policy():
    """Get password policy requirements for frontend"""
    return {
        "success": True,
        "message": "Password policy requirements",
        "data": PASSWORD_REQUIREMENTS
    }


@router.post("/check-password-strength")
def check_password_strength(payload: PasswordStrengthRequest):
    """Check password strength without storing it"""
    try:
        strength_info = PasswordPolicy.get_password_strength(payload.password)
        errors = PasswordPolicy.get_password_errors(payload.password)

        return {
            "success": True,
            "message": "Password strength analyzed",
            "data": {
                "strength": strength_info,
                "errors": errors,
                "is_valid": len(errors) == 0
            }
        }
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to analyze password strength"
        )


# ---------------- EMAIL VERIFICATION ---------------- #

@router.post("/send-verification", response_model=EmailVerificationResponse)
def send_verification_email(payload: SendVerificationRequest, db: Session = Depends(get_db)):
    """Send email verification code to user"""
    try:
        result = auth_service.send_verification_email(db, payload.email)
        return EmailVerificationResponse(
            success=True,
            message=result["message"],
            data={
                "task_id": result["task_id"],
                "expires_in_minutes": result["expires_in_minutes"]
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to send verification email"
        )


@router.post("/verify-email", response_model=EmailVerificationResponse)
def verify_email(payload: VerifyEmailRequest, db: Session = Depends(get_db)):
    """Verify user's email with verification code"""
    try:
        result = auth_service.verify_email(db, payload.email, payload.verification_code)
        return EmailVerificationResponse(
            success=True,
            message=result["message"],
            data={
                "verified_at": result["verified_at"]
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to verify email"
        )


@router.post("/resend-verification", response_model=EmailVerificationResponse)
def resend_verification_email(payload: ResendVerificationRequest, db: Session = Depends(get_db)):
    """Resend email verification code"""
    try:
        result = auth_service.send_verification_email(db, payload.email)
        return EmailVerificationResponse(
            success=True,
            message=result["message"],
            data={
                "task_id": result["task_id"],
                "expires_in_minutes": result["expires_in_minutes"]
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to resend verification email"
        )


@router.get("/verification-status/{email}", response_model=EmailVerificationResponse)
def get_verification_status(email: str, db: Session = Depends(get_db)):
    """Get email verification status for user"""
    try:
        result = auth_service.get_verification_status(db, email)
        return EmailVerificationResponse(
            success=True,
            message="Verification status retrieved",
            data=result
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get verification status"
        )


# ---------------- PASSWORD RESET ---------------- #

@router.post("/request-password-reset", response_model=PasswordResetResponse)
def request_password_reset(payload: RequestPasswordResetRequest, db: Session = Depends(get_db)):
    """Request password reset email"""
    try:
        result = auth_service.request_password_reset(db, payload.email)
        return PasswordResetResponse(
            success=True,
            message=result["message"],
            data={
                "expires_in_minutes": result["expires_in_minutes"]
            }
        )
    except Exception as e:
        # Always return success for security (prevent email enumeration)
        return PasswordResetResponse(
            success=True,
            message=f"If an account with {payload.email} exists, a password reset email has been sent",
            data={
                "expires_in_minutes": 30
            }
        )


@router.post("/reset-password", response_model=PasswordResetResponse)
def reset_password_with_code(payload: VerifyPasswordResetRequest, db: Session = Depends(get_db)):
    """Reset password using verification code"""
    try:
        result = auth_service.reset_password_with_code(
            db, payload.email, payload.reset_code, payload.new_password
        )
        return PasswordResetResponse(
            success=True,
            message=result["message"],
            data={
                "password_changed_at": result["password_changed_at"]
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to reset password"
        )
