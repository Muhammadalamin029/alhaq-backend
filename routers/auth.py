from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm, OAuth2PasswordBearer
from sqlalchemy.orm import Session
from datetime import timedelta
from core.config import settings
from core.auth import create_access_token, create_refresh_token, decode_token, hashpassword, verify_password
from db.session import get_db
from core.model import User, Profile, SellerProfile
from schemas.auth import TokenResponse, RefreshRequest, RegisterRequest, UserRole
from sqlalchemy.exc import IntegrityError
import logging

router = APIRouter()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


SECRET_KEY = settings.SECRET_KEY
REFRESH_SECRET_KEY = settings.REFRESH_SECRET_KEY
ALGORITHM = "HS256"

ACCESS_TOKEN_EXPIRE_MINUTES = settings.ACCESS_TOKEN_EXPIRE_MINUTES
REFRESH_TOKEN_EXPIRE_DAYS = 7


def generate_tokens(user_id: str, role: str):
    user_data = {"sub": user_id, "role": role}
    access_token = create_access_token(user_data, timedelta(
        minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES))
    refresh_token = create_refresh_token(
        user_data, timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS))
    return access_token, refresh_token


# ---------------- REFRESH ---------------- #
@router.post("/refresh", response_model=TokenResponse)
def refresh_tokens(refresh_request: RefreshRequest):
    try:
        payload = decode_token(
            refresh_request.refresh_token, settings.REFRESH_SECRET_KEY)
    except HTTPException:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Invalid or expired refresh token")

    user_id, role = payload.get("sub"), payload.get("role")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token data")

    access_token, refresh_token = generate_tokens(user_id, role)
    return TokenResponse(access_token=access_token, refresh_token=refresh_token)


# ---------------- LOGIN ---------------- #


@router.post("/login", response_model=TokenResponse)
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == form_data.username).first()
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    access_token, refresh_token = generate_tokens(str(user.id), user.role)
    return TokenResponse(access_token=access_token, refresh_token=refresh_token)


# ---------------- REGISTER ---------------- #

def create_user(db: Session, email: str, password: str, role: UserRole, full_name: str, bio: str):
    # Prevent admin creation via public endpoint
    if role == UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Cannot register as admin")

    hashed_password = hashpassword(password)
    user = User(email=email, hashed_password=hashed_password, role=role.value)
    db.add(user)
    db.flush()  # ensures user.id exists

    # Assign correct profile
    if role == UserRole.SELLER:
        profile = SellerProfile(
            id=user.id, business_name=full_name, description=bio)
    else:  # customer
        profile = Profile(id=user.id, name=full_name, bio=bio)

    db.add(profile)
    db.commit()
    db.refresh(user)
    return user.id


@router.post("/register/customer", status_code=201)
def register_customer(body: RegisterRequest, db: Session = Depends(get_db)):
    if body.role != UserRole.CUSTOMER:
        raise HTTPException(
            status_code=400, detail="Invalid role for this endpoint")
    try:
        user_id = create_user(db, body.email, body.password,
                              body.role, body.full_name, body.bio)
        return {"message": "Customer registered successfully", "user_id": user_id}
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="Email already registered")
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail="Something went wrong")


@router.post("/register/seller", status_code=201)
def register_seller(body: RegisterRequest, db: Session = Depends(get_db)):
    if body.role != UserRole.SELLER:
        raise HTTPException(
            status_code=400, detail="Invalid role for this endpoint")
    try:
        user_id = create_user(db, body.email, body.password,
                              body.role, body.full_name, body.bio)
        return {"message": "Seller registered successfully", "user_id": user_id}
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="Email already registered")
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail="Something went wrong")
