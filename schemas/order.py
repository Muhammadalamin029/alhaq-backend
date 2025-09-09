from pydantic import BaseModel, UUID4, Field
from typing import List, Optional
from datetime import datetime


# ----------------- SUPPORTING -----------------
class UserResponse(BaseModel):
    id: UUID4
    name: str
    email: Optional[str] = None

    class Config:
        from_attributes = True


class AddressResponse(BaseModel):
    id: UUID4
    street: str
    city: str
    state: str
    country: str

    class Config:
        from_attributes = True


class ProductResponse(BaseModel):
    id: UUID4
    name: str
    description: Optional[str] = None
    price: float
    image_url: Optional[str] = None

    class Config:
        from_attributes = True


# ---------------- ORDER ITEM -----------------
class OrderItemCreate(BaseModel):
    product_id: UUID4
    quantity: int = Field(..., gt=0)
    price: float = Field(..., gt=0)


class OrderItemResponse(BaseModel):
    id: UUID4
    quantity: int
    price: float
    product: ProductResponse   # 👈 full product nested

    class Config:
        from_attributes = True


# ---------------- ORDER -----------------
class OrderCreate(BaseModel):
    delivery_address_id: Optional[UUID4] = None
    items: List[OrderItemCreate]


class OrderResponse(BaseModel):
    id: UUID4
    total_amount: float
    status: str
    created_at: datetime
    updated_at: datetime

    buyer: UserResponse
    delivery_addr: Optional[AddressResponse] = None
    order_items: List[OrderItemResponse]

    class Config:
        from_attributes = True
