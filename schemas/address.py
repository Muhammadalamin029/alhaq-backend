from pydantic import BaseModel, Field
from typing import Optional
from uuid import UUID
from datetime import datetime


class AddressCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=50)
    street_address: str = Field(..., min_length=1, max_length=255)
    city: str = Field(..., min_length=1, max_length=100)
    state_province: str = Field(..., min_length=1, max_length=100)
    postal_code: str = Field(..., min_length=1, max_length=20)
    country: str = Field(..., min_length=1, max_length=100)
    is_default: Optional[bool] = False


class AddressUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=50)
    street_address: Optional[str] = Field(None, min_length=1, max_length=255)
    city: Optional[str] = Field(None, min_length=1, max_length=100)
    state_province: Optional[str] = Field(None, min_length=1, max_length=100)
    postal_code: Optional[str] = Field(None, min_length=1, max_length=20)
    country: Optional[str] = Field(None, min_length=1, max_length=100)
    is_default: Optional[bool] = None


class AddressResponse(BaseModel):
    id: UUID
    title: str
    street_address: str
    city: str
    state_province: str
    postal_code: str
    country: str
    is_default: bool
    created_at: datetime

    class Config:
        from_attributes = True


class AddressListResponse(BaseModel):
    success: bool
    message: str
    data: list[AddressResponse]
    pagination: dict | None = None


class AddressSingleResponse(BaseModel):
    success: bool
    message: str
    data: AddressResponse
