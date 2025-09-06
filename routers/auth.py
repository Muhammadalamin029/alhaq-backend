from fastapi.security import OAuth2PasswordBearer
from fastapi import Depends, HTTPException, status, APIRouter
from datetime import timedelta
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from datetime import timedelta
from core.config import settings
from core.auth import create_access_token, create_refresh_token, decode_token
from schemas.auth import TokenResponse, RefreshRequest
from sqlalchemy.orm import Session
from db.session import get_db
from core.model import User

router = APIRouter()

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")
SECRET_KEY = settings.SECRET_KEY
REFRESH_SECRET_KEY = settings.REFRESH_SECRET_KEY
ALGORITHM = "HS256"

ACCESS_TOKEN_EXPIRE_MINUTES = settings.ACCESS_TOKEN_EXPIRE_MINUTES
REFRESH_TOKEN_EXPIRE_DAYS = 7


# ---------------- LOGIN ---------------- #


@router.post("/login", response_model=TokenResponse)
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    # 1. Authenticate user (replace with real DB check)
    if form_data.username != "admin" or form_data.password != "secret":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )

    user_data = {"sub": "123", "role": "admin"}  # Example payload

    # 2. Generate tokens
    access_token = create_access_token(
        user_data, timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    refresh_token = create_refresh_token(
        user_data, timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS))

    return TokenResponse(access_token=access_token, refresh_token=refresh_token)


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


@router.get("/register/{email}/{role}/{password}")
def register(email, role, password, db: Session = Depends(get_db)):
    user = User(email=email, hashed_password=password)
    db.add(user)
    db.commit()
    db.refresh(user)
    return {"message": "Register endpoint - to be implemented"}


@router.get("/")
async def read_root(db: Session = Depends(get_db)):
    users = db.query(User).all()
    return users
