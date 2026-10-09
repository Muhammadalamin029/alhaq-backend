from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm, OAuth2PasswordBearer
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from pydantic import BaseModel

from core.config import settings
from core.auth import (
    create_access_token,
    create_refresh_token,
    decode_token,
    ensure_user_active,
    get_current_user,
)
from core.auth_service import auth_service
from core.model import User
from core.token_denylist import denylist_token, is_denylisted
from core.password_policy import PasswordPolicy, PASSWORD_REQUIREMENTS
from core.system_settings_service import system_settings_service
from db.session import get_db
from schemas.auth import (
    LoginRequest,
    RegisterRequest,
    TokenResponse,
    RefreshRequest,
    LogoutRequest,
    ChangePasswordRequest,
    UpdateProfileRequest,
    FullUserProfileResponse,
    VerifyEmailRequest,
    ResendVerificationRequest,
    VerifyPasswordResetRequest,
    EmailVerificationResponse,
    PasswordResetResponse,
    LoginRequest,
    SendVerificationRequest,
    RequestPasswordResetRequest,
    GoogleAuthRequest,
)
from google.oauth2 import id_token as google_id_token
from google.auth.transport import requests as google_requests
from sqlalchemy.exc import IntegrityError
from core.logging_config import get_logger, log_auth_event, log_error

# Get logger for auth routes
auth_logger = get_logger("auth")

router = APIRouter()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


def generate_tokens(db: Session, user_id: str, role: str):
    """Generate access and refresh tokens for user"""
    user_data = {"sub": user_id, "role": role}
    access_token_lifetime_minutes = (
        system_settings_service.get_access_token_lifetime_minutes(db)
    )
    access_token = create_access_token(
        user_data, timedelta(minutes=access_token_lifetime_minutes)
    )
    refresh_token = create_refresh_token(
        user_data, timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    )
    return access_token, refresh_token


# ---------------- AUTHENTICATION ---------------- #


@router.post("/refresh", response_model=TokenResponse)
def refresh_tokens(refresh_request: RefreshRequest, db: Session = Depends(get_db)):
    """Refresh access token using refresh token (single-use rotation)."""
    try:
        payload = decode_token(
            refresh_request.refresh_token, settings.REFRESH_SECRET_KEY
        )
    except HTTPException:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )

    # Reject revoked tokens (logout) and already-rotated tokens (reuse).
    if is_denylisted(refresh_request.refresh_token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session revoked. Please sign in again.",
        )

    user_id, role = payload.get("sub"), payload.get("role")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token data")

    access_token, refresh_token = generate_tokens(db, user_id, role)
    # Single-use rotation: the presented token dies here; reuse is rejected.
    denylist_token(
        refresh_request.refresh_token,
        settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400,
    )
    return TokenResponse(access_token=access_token, refresh_token=refresh_token)


@router.post("/logout")
def logout(logout_request: LogoutRequest):
    """Revoke the refresh token server-side. Always succeeds (idempotent)."""
    if logout_request.refresh_token:
        denylist_token(
            logout_request.refresh_token,
            settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400,
        )
    return {"success": True, "message": "Logged out successfully"}


@router.post("/login", response_model=TokenResponse)
def login(request: Request, form_data: LoginRequest, db: Session = Depends(get_db)):
    """Authenticate user and return tokens"""
    try:
        auth_logger.info(f"Login attempt for user: {form_data.email}")

        user, _ = auth_service.authenticate_user(
            db, form_data.email, form_data.password
        )

        # Log successful login
        log_auth_event(
            auth_logger,
            "user_login",
            email=form_data.email,
            user_id=str(user.id),
            success=True,
            user_role=user.role,
        )

        access_token, refresh_token = generate_tokens(db, str(user.id), user.role)

        # Fire-and-forget login security email (controlled by settings.SEND_LOGIN_EMAIL)
        if settings.SEND_LOGIN_EMAIL:
            try:
                from core.tasks import send_login_email
                from datetime import datetime, timezone
                from core.model import Profile

                profile = db.query(Profile).filter(Profile.id == user.id).first()
                display_name = profile.name if profile else user.email
                login_time = datetime.now(timezone.utc).strftime(
                    "%d %b %Y, %I:%M %p UTC"
                )
                # Extract real IP (respects X-Forwarded-For from reverse proxies)
                forwarded_for = request.headers.get("x-forwarded-for")
                ip_address = (
                    forwarded_for.split(",")[0].strip()
                    if forwarded_for
                    else (request.client.host if request.client else None)
                )
                # Parse a short device string from User-Agent
                ua = request.headers.get("user-agent", "")
                if "iPhone" in ua or "iPad" in ua:
                    device = "iOS Device"
                elif "Android" in ua:
                    device = "Android Device"
                elif "Windows" in ua:
                    device = "Windows"
                elif "Macintosh" in ua or "Mac OS" in ua:
                    device = "macOS"
                elif "Linux" in ua:
                    device = "Linux"
                else:
                    device = "Unknown Device"
                # Append browser if detectable
                if "Chrome" in ua and "Edg" not in ua and "OPR" not in ua:
                    device += " / Chrome"
                elif "Firefox" in ua:
                    device += " / Firefox"
                elif "Safari" in ua and "Chrome" not in ua:
                    device += " / Safari"
                elif "Edg" in ua:
                    device += " / Edge"
                send_login_email.delay(
                    user.email, display_name, login_time, ip_address, device
                )
            except Exception:
                pass  # Never block login due to email failure

        return TokenResponse(access_token=access_token, refresh_token=refresh_token)

    except HTTPException as e:
        # Log failed login attempt
        log_auth_event(
            auth_logger,
            "user_login_failed",
            email=form_data.email,
            success=False,
            reason=str(e.detail),
            status_code=e.status_code,
        )
        raise
    except Exception as e:
        log_error(
            auth_logger,
            f"Unexpected error during login for {form_data.email}",
            e,
            email=form_data.email,
        )
        raise HTTPException(status_code=500, detail="Login failed")


@router.post("/google", response_model=TokenResponse)
def google_auth(body: GoogleAuthRequest, db: Session = Depends(get_db)):
    """Authenticate (or create) a customer via a Google Sign-In ID token."""
    if not settings.GOOGLE_CLIENT_ID:
        raise HTTPException(status_code=501, detail="Google sign-in is not configured")

    try:
        claims = google_id_token.verify_oauth2_token(
            body.id_token, google_requests.Request(), settings.GOOGLE_CLIENT_ID
        )
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid Google token")

    if not claims.get("email_verified"):
        raise HTTPException(status_code=401, detail="Google email is not verified")

    google_sub = claims.get("sub")
    email = claims.get("email")
    if not google_sub or not email:
        raise HTTPException(
            status_code=401, detail="Google account did not provide a usable identity"
        )

    try:
        user = auth_service.authenticate_or_create_google_user(
            db,
            google_id=google_sub,
            email=email,
            full_name=claims.get("name", ""),
        )
    except IntegrityError:
        # A concurrent first login raced us to create the user; re-query and continue.
        db.rollback()
        user = db.query(User).filter(User.google_id == google_sub).first()
        if not user:
            raise HTTPException(status_code=401, detail="Google sign-in failed")
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        log_error(auth_logger, f"Unexpected error during Google auth for {email}", e)
        raise HTTPException(status_code=500, detail="Google sign-in failed")

    log_auth_event(
        auth_logger,
        "user_login",
        email=user.email,
        user_id=str(user.id),
        success=True,
        user_role=user.role,
    )
    access_token, refresh_token = generate_tokens(db, str(user.id), user.role)
    return TokenResponse(access_token=access_token, refresh_token=refresh_token)


# ---------------- REGISTRATION ---------------- #


@router.post("/register/customer", response_model=TokenResponse, status_code=201)
def register_customer(body: RegisterRequest, db: Session = Depends(get_db)):
    """Register a new customer and return authentication tokens"""
    try:
        auth_logger.info(f"Customer registration attempt: {body.email}")

        user_id = auth_service.create_user(
            db,
            body.email,
            body.password,
            "customer",
            body.full_name,
            body.phone,
            body.bio,
        )

        # Log successful registration
        log_auth_event(
            auth_logger,
            "customer_registration",
            email=body.email,
            user_id=user_id,
            success=True,
            user_role="customer",
        )

        # Generate tokens for immediate login after registration
        access_token, refresh_token = generate_tokens(db, user_id, "customer")
        return TokenResponse(access_token=access_token, refresh_token=refresh_token)

    except IntegrityError as e:
        db.rollback()
        log_auth_event(
            auth_logger,
            "customer_registration_failed",
            email=body.email,
            success=False,
            reason="Email already registered",
        )
        raise HTTPException(status_code=400, detail="Email already registered")
    except HTTPException as e:
        log_auth_event(
            auth_logger,
            "customer_registration_failed",
            email=body.email,
            success=False,
            reason=str(e.detail),
        )
        raise
    except Exception as e:
        db.rollback()
        log_error(
            auth_logger,
            f"Customer registration failed for {body.email}",
            e,
            email=body.email,
        )
        raise HTTPException(status_code=500, detail="Registration failed")


# ---------------- PROFILE MANAGEMENT ---------------- #


@router.get("/me", response_model=FullUserProfileResponse)
def get_current_user_profile(
    current_user=Depends(get_current_user), db: Session = Depends(get_db)
):
    """Get current authenticated user's profile"""
    try:
        ensure_user_active(db, current_user["id"])
        auth_logger.debug(f"Profile fetch request for user: {current_user['id']}")

        profile_data = auth_service.get_user_profile(db, current_user["id"])

        auth_logger.info(f"Profile fetched successfully for user: {current_user['id']}")
        return FullUserProfileResponse(**profile_data)

    except HTTPException:
        raise
    except Exception as e:
        log_error(
            auth_logger,
            f"Failed to fetch profile for user {current_user['id']}",
            e,
            user_id=current_user["id"],
        )
        raise HTTPException(status_code=500, detail="Failed to fetch profile")


@router.delete("/me", status_code=200)
def delete_current_user_account(
    current_user=Depends(get_current_user), db: Session = Depends(get_db)
):
    """
    Request Play-compliant account deletion (30-day grace period).

    - Blocks login immediately (is_active=False, enforced in auth_service).
    - Revokes push tokens immediately.
    - Personal data is permanently deleted/anonymized after 30 days by the
      purge job (services/purge_deleted_accounts.py).
    - Anonymized escrow/financial ledgers are retained up to 7 years for
      AML / tax / deed-tracing compliance and cannot be expunged.
    - Idempotent: repeating the call returns the existing schedule.
    """
    from core.model import PushDeviceToken as PushDeviceTokenModel
    from core.model import User as UserModel

    try:
        user = db.query(UserModel).filter(UserModel.id == current_user["id"]).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        now = datetime.utcnow()
        if getattr(user, "is_active", True) is False and getattr(user, "deleted_at", None):
            return {
                "success": True,
                "message": "Account deletion already scheduled.",
                "data": {
                    "deleted_at": user.deleted_at.isoformat() if user.deleted_at else None,
                    "retention_note": "Personal data purged 30 days after request. Anonymized escrow/financial ledgers retained up to 7 years for legal compliance.",
                },
            }

        purge_due = now + timedelta(days=30)
        user.is_active = False
        user.deletion_requested_at = now
        user.deleted_at = purge_due
        # Revoke push tokens immediately so deleted users get no notifications.
        db.query(PushDeviceTokenModel).filter(
            PushDeviceTokenModel.user_id == user.id
        ).delete(synchronize_session=False)
        db.commit()

        auth_logger.info(f"Account deletion scheduled for user: {current_user['id']} due {purge_due.isoformat()}")
        return {
            "success": True,
            "message": "Account deletion scheduled. Your personal data will be permanently deleted in 30 days.",
            "data": {
                "deleted_at": purge_due.isoformat(),
                "retention_note": "Personal data purged 30 days after request. Anonymized escrow/financial ledgers retained up to 7 years for legal compliance.",
            },
        }

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        log_error(
            auth_logger,
            f"Failed to delete account for user {current_user['id']}",
            e,
            user_id=current_user["id"],
        )
        raise HTTPException(status_code=500, detail="Failed to schedule account deletion")


@router.post("/me/restore", status_code=200)
def restore_deleted_account(
    current_user=Depends(get_current_user), db: Session = Depends(get_db)
):
    """Restore an account within the 30-day grace period (re-activates login)."""
    from core.model import User as UserModel

    user = db.query(UserModel).filter(UserModel.id == current_user["id"]).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if getattr(user, "is_active", True) is True:
        return {"success": True, "message": "Account is already active."}
    # Past purge date cannot be restored (purge job owns final deletion).
    user.is_active = True
    user.deletion_requested_at = None
    user.deleted_at = None
    db.commit()
    auth_logger.info(f"Account restored for user: {current_user['id']}")
    return {"success": True, "message": "Account restored successfully."}


@router.get("/me/export", status_code=200)
def export_current_user_data(
    current_user=Depends(get_current_user), db: Session = Depends(get_db)
):
    """NDPR right to data portability: JSON dump of account + related rows."""
    from core.model import (
        Address as AddressModel,
        Profile as ProfileModel,
        User as UserModel,
    )

    user = db.query(UserModel).filter(UserModel.id == current_user["id"]).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    profile = db.query(ProfileModel).filter(ProfileModel.id == user.id).first()
    addresses = db.query(AddressModel).filter(AddressModel.user_id == user.id).all()
    return {
        "success": True,
        "data": {
            "user": {
                "id": str(user.id),
                "email": user.email,
                "role": user.role,
                "email_verified": user.email_verified,
                "is_active": user.is_active,
                "deletion_requested_at": user.deletion_requested_at.isoformat() if getattr(user, "deletion_requested_at", None) else None,
                "deleted_at": user.deleted_at.isoformat() if getattr(user, "deleted_at", None) else None,
                "created_at": user.created_at.isoformat() if user.created_at else None,
            },
            "profile": {
                "name": profile.name if profile else None,
                "phone": profile.phone if profile else None,
                "bio": profile.bio if profile else None,
                "avatar_url": profile.avatar_url if profile else None,
                "kyc_status": profile.kyc_status if profile else None,
            } if profile else None,
            "addresses": [
                {
                    "title": a.title,
                    "street_address": a.street_address,
                    "city": a.city,
                    "state_province": a.state_province,
                    "postal_code": a.postal_code,
                    "country": a.country,
                }
                for a in addresses
            ],
            "retention_note": "Escrow/financial ledgers retained anonymized up to 7 years for legal compliance.",
        },
    }


@router.put("/me", response_model=FullUserProfileResponse)
def update_current_user_profile(
    payload: UpdateProfileRequest,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update current authenticated user's profile"""
    try:
        ensure_user_active(db, current_user["id"])
        update_data = payload.model_dump(exclude_unset=True)

        auth_logger.info(
            f"Profile update request for user: {current_user['id']}",
            extra={
                "user_id": current_user["id"],
                "update_fields": list(update_data.keys()),
            },
        )

        print(update_data)

        profile_data = auth_service.update_user_profile(
            db, current_user["id"], update_data
        )

        auth_logger.info(f"Profile updated successfully for user: {current_user['id']}")
        return FullUserProfileResponse(**profile_data)

    except HTTPException:
        raise
    except Exception as e:
        log_error(
            auth_logger,
            f"Failed to update profile for user {current_user['id']}",
            e,
            user_id=current_user["id"],
            update_fields=list(update_data.keys()) if "update_data" in locals() else [],
        )
        raise HTTPException(status_code=500, detail="Failed to update profile")


@router.put("/change-password", status_code=status.HTTP_200_OK)
def change_password(
    payload: ChangePasswordRequest,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Change user's password"""
    try:
        auth_logger.info(f"Password change request for user: {current_user['id']}")

        password_data = auth_service.change_user_password(
            db, current_user["id"], payload.current_password, payload.new_password
        )

        # Log successful password change
        log_auth_event(
            auth_logger, "password_change", user_id=current_user["id"], success=True
        )

        return {
            "success": True,
            "message": "Password changed successfully",
            "data": password_data,
        }

    except HTTPException as e:
        # Log failed password change
        log_auth_event(
            auth_logger,
            "password_change_failed",
            user_id=current_user["id"],
            success=False,
            reason=str(e.detail),
        )
        raise
    except Exception as e:
        log_error(
            auth_logger,
            f"Password change failed for user {current_user['id']}",
            e,
            user_id=current_user["id"],
        )
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
        "data": PASSWORD_REQUIREMENTS,
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
                "is_valid": len(errors) == 0,
            },
        }
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to analyze password strength",
        )


# ---------------- EMAIL VERIFICATION ---------------- #


@router.post("/send-verification", response_model=EmailVerificationResponse)
def send_verification_email(
    payload: SendVerificationRequest, db: Session = Depends(get_db)
):
    """Send email verification code to user"""
    try:
        result = auth_service.send_verification_email(db, payload.email)
        return EmailVerificationResponse(
            success=True,
            message=result["message"],
            data={
                "task_id": result["task_id"],
                "expires_in_minutes": result["expires_in_minutes"],
            },
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to send verification email",
        )


@router.post("/verify-email", response_model=EmailVerificationResponse)
def verify_email(payload: VerifyEmailRequest, db: Session = Depends(get_db)):
    """Verify user's email with verification code"""
    try:
        result = auth_service.verify_email(db, payload.email, payload.verification_code)
        return EmailVerificationResponse(
            success=True,
            message=result["message"],
            data={"verified_at": result["verified_at"]},
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to verify email",
        )


@router.post("/resend-verification", response_model=EmailVerificationResponse)
def resend_verification_email(
    payload: ResendVerificationRequest, db: Session = Depends(get_db)
):
    """Resend email verification code"""
    try:
        result = auth_service.send_verification_email(db, payload.email)
        return EmailVerificationResponse(
            success=True,
            message=result["message"],
            data={
                "task_id": result["task_id"],
                "expires_in_minutes": result["expires_in_minutes"],
            },
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to resend verification email",
        )


@router.get("/verification-status/{email}", response_model=EmailVerificationResponse)
def get_verification_status(email: str, db: Session = Depends(get_db)):
    """Get email verification status for user"""
    try:
        result = auth_service.get_verification_status(db, email)
        return EmailVerificationResponse(
            success=True, message="Verification status retrieved", data=result
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get verification status",
        )


# ---------------- PASSWORD RESET ---------------- #


@router.post("/request-password-reset", response_model=PasswordResetResponse)
def request_password_reset(
    payload: RequestPasswordResetRequest, db: Session = Depends(get_db)
):
    """Request password reset email"""
    try:
        result = auth_service.request_password_reset(db, payload.email)
        return PasswordResetResponse(
            success=True,
            message=result["message"],
            data={"expires_in_minutes": result["expires_in_minutes"]},
        )
    except HTTPException:
        raise
    except Exception as e:
        # Always return success for security (prevent email enumeration)
        return PasswordResetResponse(
            success=True,
            message=f"If an account with {payload.email} exists, a password reset email has been sent",
            data={"expires_in_minutes": 30},
        )


@router.post("/reset-password", response_model=PasswordResetResponse)
def reset_password_with_code(
    payload: VerifyPasswordResetRequest, db: Session = Depends(get_db)
):
    """Reset password using verification code"""
    try:
        result = auth_service.reset_password_with_code(
            db, payload.email, payload.reset_code, payload.new_password
        )
        return PasswordResetResponse(
            success=True,
            message=result["message"],
            data={"password_changed_at": result["password_changed_at"]},
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to reset password",
        )
