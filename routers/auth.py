from fastapi.security import OAuth2PasswordBearer
from fastapi import Depends, HTTPException, status, APIRouter
from datetime import timedelta
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from datetime import timedelta
from core.config import settings
from core.auth import create_access_token, create_refresh_token, decode_token, hashpassword, verify_password
from schemas.auth import TokenResponse, RefreshRequest, RegisterRequest
from sqlalchemy.orm import Session
from db.session import get_db
from core.model import User, Profile, SellerProfile
from sqlalchemy.exc import IntegrityError


router = APIRouter()

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")
SECRET_KEY = settings.SECRET_KEY
REFRESH_SECRET_KEY = settings.REFRESH_SECRET_KEY
ALGORITHM = "HS256"

ACCESS_TOKEN_EXPIRE_MINUTES = settings.ACCESS_TOKEN_EXPIRE_MINUTES
REFRESH_TOKEN_EXPIRE_DAYS = 7


# ---------------- REFRESH ---------------- #
@router.post("/refresh", response_model=TokenResponse)
def refresh_tokens(refresh_request: RefreshRequest):
    try:
        payload = decode_token(
            refresh_request.refresh_token, REFRESH_SECRET_KEY)
    except HTTPException:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )

    user_data = {"sub": payload.get("sub"), "role": payload.get("role")}
    if not user_data["sub"]:
        raise HTTPException(status_code=401, detail="Invalid token data")

    # Issue new tokens
    access_token = create_access_token(
        user_data, timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    refresh_token = create_refresh_token(
        user_data, timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS))

    return TokenResponse(access_token=access_token, refresh_token=refresh_token)

# ---------------- LOGIN ---------------- #


@router.post("/login", response_model=TokenResponse)
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    try:
        # 1. Authenticate user
        user = db.query(User).filter(User.email == form_data.username).first()
        if not user or not verify_password(form_data.password, user.hashed_password):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid username or password",
            )

        # 2. Token payload
        user_data = {"sub": str(user.id), "role": user.role}

        # 3. Generate tokens
        access_token = create_access_token(
            user_data, timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
        )
        refresh_token = create_refresh_token(
            user_data, timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
        )

        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "bearer"
        }

    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Something went wrong"
        )


# ---------------- REGISTER ---------------- #


@router.post("/register", status_code=201)
def register(body: RegisterRequest, db: Session = Depends(get_db)):
    try:
        hashed_password = hashpassword(body.password)

        user = User(
            email=body.email,
            hashed_password=hashed_password,
            role=body.role
        )
        db.add(user)
        db.flush()

        profile = Profile(
            id=user.id,
            name=body.full_name,
            bio=body.bio
        )
        db.add(profile)

        db.commit()
        db.refresh(user)

        return {"message": "User registered successfully", "user_id": user.id}

    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Email already registered"
        )

    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Something went wrong"
        )


@router.post("/seller/register", status_code=201)
def seller_register(body: RegisterRequest, db: Session = Depends(get_db)):
    try:
        hashed_password = hashpassword(body.password)

        user = User(
            email=body.email,
            hashed_password=hashed_password,
            role=body.role
        )
        db.add(user)
        db.flush()

        profile = SellerProfile(
            id=user.id,
            business_name=body.full_name,
            description=body.bio
        )
        db.add(profile)

        db.commit()
        db.refresh(user)

        return {"message": "User registered successfully", "user_id": user.id}

    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Email already registered"
        )

    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Something went wrong"
        )


@router.get("/")
async def read_root(db: Session = Depends(get_db)):
    users = db.query(User).all()
    profiles = db.query(Profile).all()
    return {
        "users": users,
        "profiles": profiles
    }
