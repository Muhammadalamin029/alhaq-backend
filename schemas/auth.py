from enum import Enum
from pydantic import BaseModel, EmailStr, Field, validator, UUID4
from typing import Optional, Union, Dict
from datetime import datetime, date

# ---------------- SCHEMAS ---------------- #


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str


class UserRole(str, Enum):
    CUSTOMER = "customer"
    SELLER = "seller"
    ADMIN = "admin"

class LoginRequest(BaseModel):
    email: str
    password: str = Field(..., min_length=8)


class RegisterRequest(BaseModel):
    email: str
    password: str = Field(..., min_length=8)
    full_name: str
    bio: str = None


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(..., min_length=8)
    confirm_password: str
    
    @validator('confirm_password')
    def passwords_match(cls, v, values):
        if 'new_password' in values and v != values['new_password']:
            raise ValueError('Passwords do not match')
        return v


class UpdateProfileRequest(BaseModel):
    # Shared
    email: Optional[EmailStr] = None

    # Customer fields
    firstName: Optional[str] = Field(None, min_length=1, max_length=100, strip_whitespace=True)
    lastName: Optional[str] = Field(None, min_length=1, max_length=100, strip_whitespace=True)
    bio: Optional[str] = Field(None, max_length=1000, strip_whitespace=True)
    avatar_url: Optional[str] = None

    # Seller/Admin fields
    business_name: Optional[str] = Field(None, min_length=1, max_length=255, strip_whitespace=True)
    description: Optional[str] = Field(None, max_length=2000, strip_whitespace=True)
    contact_email: Optional[EmailStr] = None
    contact_phone: Optional[str] = Field(None, min_length=7, max_length=20, strip_whitespace=True)
    website_url: Optional[str] = None
    logo_url: Optional[str] = None

    class Config:
        orm_mode = True


class UserProfileResponse(BaseModel):
    id: UUID4
    email: str
    role: str
    email_verified: bool
    created_at: datetime
    updated_at: datetime
    last_login: Optional[datetime] = None
    password_changed_at: datetime
    two_factor_enabled: bool
    
    class Config:
        from_attributes = True


class CustomerProfileResponse(BaseModel):
    id: UUID4
    name: str
    bio: Optional[str] = None
    kyc_status: str
    approval_date: Optional[date] = None
    avatar_url: Optional[str] = None
    created_at: datetime
    
    class Config:
        from_attributes = True


class SellerProfileResponse(BaseModel):
    id: UUID4
    business_name: str
    description: Optional[str] = None
    logo_url: Optional[str] = None
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    website_url: Optional[str] = None
    kyc_status: str
    approval_date: Optional[date] = None
    total_products: int
    total_orders: int
    total_revenue: float
    created_at: datetime
    
    class Config:
        from_attributes = True


class FullUserProfileResponse(BaseModel):
    user: UserProfileResponse
    profile: Union[CustomerProfileResponse, SellerProfileResponse, None] = None
    
    class Config:
        from_attributes = True


# ---------------- EMAIL VERIFICATION SCHEMAS ---------------- #

class SendVerificationRequest(BaseModel):
    email: EmailStr
    
    
class VerifyEmailRequest(BaseModel):
    email: EmailStr
    verification_code: str = Field(..., min_length=6, max_length=6, pattern=r'^\d{6}$')
    
    
class ResendVerificationRequest(BaseModel):
    email: EmailStr


# ---------------- PASSWORD RESET SCHEMAS ---------------- #

class RequestPasswordResetRequest(BaseModel):
    email: EmailStr
    
    
class VerifyPasswordResetRequest(BaseModel):
    email: EmailStr
    reset_code: str = Field(..., min_length=6, max_length=6, pattern=r'^\d{6}$')
    new_password: str = Field(..., min_length=8)
    confirm_password: str
    
    @validator('confirm_password')
    def passwords_match(cls, v, values):
        if 'new_password' in values and v != values['new_password']:
            raise ValueError('Passwords do not match')
        return v


# ---------------- RESPONSE SCHEMAS ---------------- #

class EmailVerificationResponse(BaseModel):
    success: bool
    message: str
    data: Optional[Dict] = None
    
    
class PasswordResetResponse(BaseModel):
    success: bool
    message: str
    data: Optional[Dict] = None
