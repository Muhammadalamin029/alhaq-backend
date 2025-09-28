from pydantic import BaseModel, Field
from typing import Optional
from uuid import UUID
from decimal import Decimal


class CheckoutRequest(BaseModel):
    delivery_address_id: UUID
    notes: Optional[str] = Field(None, max_length=500)


class CheckoutSummary(BaseModel):
    subtotal: Decimal
    shipping_fee: Decimal
    tax: Decimal
    total: Decimal
    items_count: int


class CheckoutResponse(BaseModel):
    success: bool
    message: str
    data: dict  # Will contain order details and checkout summary


class OrderConfirmation(BaseModel):
    order_id: UUID
    total_amount: Decimal
    status: str
    estimated_delivery: Optional[str]
    tracking_number: Optional[str]


class OrderConfirmationResponse(BaseModel):
    success: bool
    message: str
    data: OrderConfirmation
