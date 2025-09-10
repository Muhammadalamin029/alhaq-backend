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
    TokenResponse, RefreshRequest, RegisterRequest, UserRole,
    ChangePasswordRequest, UpdateProfileRequest, FullUserProfileResponse
)
from sqlalchemy.exc import IntegrityError

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
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    """Authenticate user and return tokens"""
    user, _ = auth_service.authenticate_user(
        db, form_data.username, form_data.password)

    access_token, refresh_token = generate_tokens(str(user.id), user.role)
    return TokenResponse(access_token=access_token, refresh_token=refresh_token)


# ---------------- REGISTRATION ---------------- #

@router.post("/register/customer", status_code=201)
def register_customer(body: RegisterRequest, db: Session = Depends(get_db)):
    """Register a new customer"""
    if body.role != UserRole.CUSTOMER:
        raise HTTPException(
            status_code=400, detail="Invalid role for this endpoint")

    try:
        user_id = auth_service.create_user(
            db, body.email, body.password, body.role, body.full_name, body.bio
        )
        return {
            "success": True,
            "message": "Customer registered successfully",
            "data": {"user_id": user_id}
        }
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="Email already registered")
    except HTTPException:
        raise
    except Exception:
        db.rollback()
        raise HTTPException(status_code=500, detail="Registration failed")


@router.post("/register/seller", status_code=201)
def register_seller(body: RegisterRequest, db: Session = Depends(get_db)):
    """Register a new seller"""
    if body.role != UserRole.SELLER:
        raise HTTPException(
            status_code=400, detail="Invalid role for this endpoint")

    try:
        user_id = auth_service.create_user(
            db, body.email, body.password, body.role, body.full_name, body.bio
        )
        return {
            "success": True,
            "message": "Seller registered successfully",
            "data": {"user_id": user_id}
        }
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="Email already registered")
    except HTTPException:
        raise
    except Exception:
        db.rollback()
        raise HTTPException(status_code=500, detail="Registration failed")


# ---------------- PROFILE MANAGEMENT ---------------- #

@router.get("/me", response_model=FullUserProfileResponse)
def get_current_user_profile(
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get current authenticated user's profile"""
    profile_data = auth_service.get_user_profile(db, current_user["id"])
    return FullUserProfileResponse(**profile_data)


@router.put("/me", response_model=FullUserProfileResponse)
def update_current_user_profile(
    payload: UpdateProfileRequest,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update current authenticated user's profile"""
    update_data = payload.model_dump(exclude_unset=True)
    profile_data = auth_service.update_user_profile(
        db, current_user["id"], update_data)
    return FullUserProfileResponse(**profile_data)


@router.put("/change-password", status_code=status.HTTP_200_OK)
def change_password(
    payload: ChangePasswordRequest,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Change user's password"""
    password_data = auth_service.change_user_password(
        db, current_user["id"], payload.current_password, payload.new_password
    )

    return {
        "success": True,
        "message": "Password changed successfully",
        "data": password_data
    }


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
