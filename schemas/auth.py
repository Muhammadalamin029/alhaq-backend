from pydantic import BaseModel

# ---------------- SCHEMAS ---------------- #


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str


class RegisterRequest(BaseModel):
    email: str
    role: str
    password: str
    full_name: str = None
    bio: str = None
