from jose import jwt, JWTError, ExpiredSignatureError
from fastapi.security import OAuth2PasswordBearer
from typing import Optional, Dict, Any
from datetime import datetime, timedelta, timezone
from fastapi import HTTPException, status, Depends
from core.config import settings
from passlib.context import CryptContext
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")
SECRET_KEY = settings.SECRET_KEY
REFRESH_SECRET_KEY = settings.REFRESH_SECRET_KEY
ALGORITHM = settings.ALGORITHM

ACCESS_TOKEN_EXPIRE_MINUTES = settings.ACCESS_TOKEN_EXPIRE_MINUTES
REFRESH_TOKEN_EXPIRE_DAYS = 7

pwd_context = CryptContext(
    schemes=["argon2"],
    deprecated="auto",
    argon2__memory_cost=19456,  # ~19 MiB (OWASP minimum for Argon2id)
    argon2__time_cost=2,
    argon2__parallelism=1,      # single thread (small shared hosts)
)


# ---------------- TOKEN CREATION ---------------- #


def create_access_token(data: Dict[str, Any], expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def create_refresh_token(data: Dict[str, Any], expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, REFRESH_SECRET_KEY, algorithm=ALGORITHM)


# ---------------- TOKEN DECODING ---------------- #
def decode_token(token: str, secret: str) -> Dict[str, Any]:
    try:
        payload = jwt.decode(token, secret, algorithms=[ALGORITHM])
        return payload
    except ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
        )
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
        )


# ---------------- HASHING PASSWORD --------------- #
def hashpassword(pwd: str):
    hashed_pwd = pwd_context.hash(pwd)

    return hashed_pwd


def verify_password(pwd: str, hsd_pwd: str) -> bool:
    return pwd_context.verify(pwd, hsd_pwd)


# ---------------- USER DEPENDENCY ---------------- #


def get_current_user(token: str = Depends(oauth2_scheme)) -> Dict[str, Any]:
    payload = decode_token(token, SECRET_KEY)
    user_id: str | None = payload.get("sub")
    role: str | None = payload.get("role")

    if user_id is None or role is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
        )

    # Re-validate against the DB so soft-deleted accounts and role changes
    # (e.g. admin demotion) take effect before the JWT itself expires.
    # Lazy import avoids a hard core.auth -> db.session import cycle.
    from db.session import SessionLocal

    db = SessionLocal()
    try:
        ensure_user_active(db, user_id, role)
    finally:
        db.close()

    return {"id": user_id, "role": role}


# ---------------- ROLE CHECK ---------------- #
def role_required(required_roles: list):
    def wrapper(user=Depends(get_current_user)):
        if user["role"] not in required_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not enough permissions",
            )
        return user
    return wrapper


def ensure_user_active(db, user_id: str, role: Optional[str] = None) -> None:
    """Raise 401/403 if the account is pending deletion or its role changed.

    Call from routes that must reject stale tokens issued before DELETE
    /auth/me or an admin role change. Login/refresh paths already block via
    auth_service; this covers access tokens still valid within their window.
    Unknown users (no row) pass through — downstream queries handle them.
    """
    from core.model import User as UserModel

    user = db.query(UserModel).filter(UserModel.id == user_id).first()
    if user is None:
        return
    if getattr(user, "is_active", True) is False:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Account scheduled for deletion. Restore within 30 days to continue.",
        )
    if role is not None and getattr(user, "role", role) != role:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permissions changed. Please sign in again.",
        )


def get_current_active_user(
    user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    """Drop-in replacement for get_current_user that also blocks deleted accounts."""
    from db.session import get_db as _get_db

    db = next(_get_db())
    try:
        ensure_user_active(db, user["id"])
    finally:
        try:
            db.close()
        except Exception:
            pass
    return user
