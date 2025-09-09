from pydantic import BaseModel, Field, UUID4
from typing import Optional, List
from uuid import UUID


class ProductImage(BaseModel):
    url: str

    class Config:
        from_attributes = True


class ProductCreate(BaseModel):
    name: str = Field(..., max_length=255)
    description: Optional[str] = None
    price: float = Field(..., gt=0)
    stock_quantity: int = Field(0, ge=0)
    category_id: UUID4
    images: Optional[List[ProductImage]] = []

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
    seller: SellerResponse
    category: CategoryResponse

    class Config:
        from_attributes = True
