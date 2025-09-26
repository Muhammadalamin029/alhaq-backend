from pydantic import BaseModel, Field, EmailStr
from typing import Optional
from uuid import UUID


class ProfileUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    phone: Optional[str] = Field(None, max_length=20)
    bio: Optional[str] = Field(None, max_length=500)


class PasswordChange(BaseModel):
    current_password: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=8, max_length=128)
    confirm_password: str = Field(..., min_length=8, max_length=128)


class ProfileResponse(BaseModel):
    id: UUID
    name: str
    phone: Optional[str]
    bio: Optional[str]
    created_at: str
    updated_at: Optional[str]
    
    class Config:
        from_attributes = True


class UserResponse(BaseModel):
    id: UUID
    email: EmailStr
    is_verified: bool
    role: str
    created_at: str
    profile: ProfileResponse
    
    class Config:
        from_attributes = True


class ProfileUpdateResponse(BaseModel):
    success: bool
    message: str
    data: UserResponse


class PasswordChangeResponse(BaseModel):
    success: bool
    message: str
