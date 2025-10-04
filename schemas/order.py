from pydantic import BaseModel, Field, validator
from typing import List, Optional
from uuid import UUID
from datetime import datetime
from pydantic.types import UUID4
from enum import Enum
from schemas.products import ProductResponse, SellerResponse


# ----------------- ENUMS -----------------
class OrderStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    PAID = "paid"
    SHIPPED = "shipped"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"


# ----------------- SUPPORTING -----------------
class UserResponse(BaseModel):
    id: UUID4
    name: str
    email: Optional[str] = None

    class Config:
        from_attributes = True


class AddressResponse(BaseModel):
    id: UUID4
    # Use FE-friendly names but map to BE model fields via aliases
    street: str = Field(alias="street_address")
    city: str
    state: str = Field(alias="state_province")
    postal_code: str
    country: str

    class Config:
        from_attributes = True



# ---------------- ORDER ITEM -----------------
class OrderItemCreate(BaseModel):
    product_id: UUID4
    quantity: int = Field(..., gt=0, le=1000, description="Quantity must be between 1 and 1000")


class OrderItemResponse(BaseModel):
    id: UUID4
    quantity: int
    price: float
    status: str = "pending"  # Item-level status
    product: ProductResponse   # 👈 full product nested

    class Config:
        from_attributes = True


# ---------------- ORDER -----------------
class OrderCreate(BaseModel):
    delivery_address_id: Optional[UUID4] = None
    items: List[OrderItemCreate]


class SellerGroupResponse(BaseModel):
    seller: Optional[SellerResponse] = None  # Seller profile information
    items: List[OrderItemResponse]
    total_amount: float
    item_count: int

    class Config:
        from_attributes = True


class OrderResponse(BaseModel):
    id: UUID4
    total_amount: float
    status: str
    seller_item_status: Optional[str] = None  # Status of this seller's items in the order
    created_at: datetime
    updated_at: datetime

    buyer: UserResponse
    delivery_addr: Optional[AddressResponse] = None
    order_items: List[OrderItemResponse]
    seller_groups: Optional[List[dict]] = None  # For customer orders - use dict for now

    class Config:
        from_attributes = True


# ----------------- ORDER STATUS MANAGEMENT -----------------
class OrderStatusUpdate(BaseModel):
    status: OrderStatus
    notes: Optional[str] = Field(None, max_length=500, description="Optional status update notes")
    
    @validator('status')
    def validate_status_transition(cls, v):
        # This will be further validated in the service layer with current status
        allowed_statuses = [status.value for status in OrderStatus]
        if v not in allowed_statuses:
            raise ValueError(f"Invalid status. Must be one of: {allowed_statuses}")
        return v


class OrderStatusResponse(BaseModel):
    success: bool
    message: str
    data: Optional[dict] = None


class BulkOrderStatusUpdate(BaseModel):
    order_ids: List[UUID4] = Field(..., min_items=1, max_items=50, description="List of order IDs to update")
    status: OrderStatus
    notes: Optional[str] = Field(None, max_length=500, description="Optional notes for all orders")
