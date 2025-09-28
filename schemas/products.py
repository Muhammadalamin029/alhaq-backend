from pydantic import BaseModel, Field, UUID4
from typing import Optional, List
from uuid import UUID
from datetime import datetime


class ProductImageSchema(BaseModel):
    """Schema for product image data"""
    image_url: str
    product_id: UUID

    class Config:
        from_attributes = True


class ProductImageCreate(BaseModel):
    """Schema for creating product images (without product_id)"""
    image_url: str

    class Config:
        from_attributes = True


class ProductCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255, strip_whitespace=True)
    description: Optional[str] = Field(None, max_length=2000, strip_whitespace=True)
    price: float = Field(..., gt=0, description="Product price must be greater than 0")
    stock_quantity: int = Field(0, ge=0, description="Stock quantity cannot be negative")
    category_id: UUID4
    images: Optional[List[ProductImageCreate]] = None

    class Config:
        from_attributes = True



class ProductUpdate(BaseModel):
    name: Optional[str] = Field(
        None, min_length=1, max_length=255, strip_whitespace=True)
    description: Optional[str] = Field(
        None, max_length=2000, strip_whitespace=True)
    price: Optional[float] = Field(
        None, gt=0, description="Product price must be greater than 0")
    stock_quantity: Optional[int] = Field(
        None, ge=0, description="Stock quantity cannot be negative")
    category_id: Optional[UUID4] = None
    status: Optional[str] = Field(
        None, pattern="^(active|inactive|out_of_stock)$")
    images: Optional[List[ProductImageSchema]] = None

    class Config:
        from_attributes = True


class CategoryResponse(BaseModel):
    id: UUID
    name: str

    class Config:
        from_attributes = True


class SellerResponse(BaseModel):
    id: UUID
    business_name: str
    description: Optional[str] = None
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    total_products: Optional[int] = None
    logo_url: Optional[str] = None
    website_url: Optional[str] = None

    class Config:
        from_attributes = True


class ProductResponse(BaseModel):
    id: UUID
    name: str
    description: Optional[str]
    price: float
    stock_quantity: int
    status: str
    created_at: datetime
    updated_at: datetime
    seller: SellerResponse
    category: CategoryResponse
    images: Optional[List[ProductImageSchema]] = []

    class Config:
        from_attributes = True
