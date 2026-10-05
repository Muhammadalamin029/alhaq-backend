from pydantic import BaseModel, Field, UUID4
from typing import Optional, List
from uuid import UUID
from datetime import datetime
from schemas.media import AssetImageResponse, AssetImageCreate




class ProductCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255, strip_whitespace=True)
    description: Optional[str] = Field(None, max_length=2000, strip_whitespace=True)
    price: float = Field(..., gt=0, description="Product price must be greater than 0")
    stock_quantity: int = Field(0, ge=0, description="Stock quantity cannot be negative")
    category_id: UUID4
    amenities: Optional[List[str]] = Field(None, max_length=50, description="Feature/amenity tags")
    images: Optional[List[AssetImageCreate]] = None
    # Discount: percent and/or sale price (sale_price wins when both given).
    discount_percent: Optional[float] = Field(None, ge=0, le=90)
    sale_price: Optional[float] = Field(None, gt=0)
    discount_starts_at: Optional[datetime] = None
    discount_ends_at: Optional[datetime] = None

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
    amenities: Optional[List[str]] = Field(
        None, max_length=50, description="Feature/amenity tags")
    images: Optional[List[AssetImageCreate]] = None
    discount_percent: Optional[float] = Field(None, ge=0, le=90)
    sale_price: Optional[float] = Field(None, gt=0)
    discount_starts_at: Optional[datetime] = None
    discount_ends_at: Optional[datetime] = None
    # Set true to remove an existing discount window/value.
    clear_discount: Optional[bool] = None

    class Config:
        from_attributes = True


class CategoryResponse(BaseModel):
    id: UUID
    name: str

    class Config:
        from_attributes = True


class ProductResponse(BaseModel):
    id: UUID
    name: str
    description: Optional[str]
    price: float
    stock_quantity: int
    status: str
    amenities: Optional[List[str]] = []
    discount_percent: Optional[float] = None
    discount_starts_at: Optional[datetime] = None
    discount_ends_at: Optional[datetime] = None
    effective_price: float = 0
    is_on_sale: bool = False
    created_at: datetime
    updated_at: datetime
    category: CategoryResponse
    images: Optional[List[AssetImageResponse]] = []

    @classmethod
    def with_discount(cls, product) -> "ProductResponse":
        from core.discounts import effective_price as _eff, is_on_sale as _sale
        base = cls.model_validate(product)
        pct = getattr(product, "discount_percent", None)
        starts = getattr(product, "discount_starts_at", None)
        ends = getattr(product, "discount_ends_at", None)
        on_sale = bool(_sale(pct, starts, ends))
        eff = float(_eff(float(product.price), pct, starts, ends))
        base.effective_price = eff
        base.is_on_sale = on_sale
        base.discount_percent = float(pct) if pct is not None else None
        return base

    class Config:
        from_attributes = True
