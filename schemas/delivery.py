from pydantic import BaseModel, Field
from typing import Optional
from uuid import UUID
from decimal import Decimal
from datetime import datetime


class DeliveryStateCreate(BaseModel):
    state_name: str = Field(..., max_length=100)
    delivery_price: Optional[Decimal] = None
    is_active: bool = True


class DeliveryStateUpdate(BaseModel):
    state_name: Optional[str] = Field(None, max_length=100)
    delivery_price: Optional[Decimal] = None
    is_active: Optional[bool] = None


class DeliveryStateResponse(BaseModel):
    id: UUID
    state_name: str
    delivery_price: Optional[Decimal]
    is_active: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class DeliverySettingsUpdate(BaseModel):
    base_delivery_price: Optional[Decimal] = None
    store_pickup_location: Optional[str] = None
    store_pickup_address: Optional[str] = None


class DeliverySettingsResponse(BaseModel):
    base_delivery_price: Decimal
    store_pickup_location: Optional[str]
    store_pickup_address: Optional[str]

    class Config:
        from_attributes = True
