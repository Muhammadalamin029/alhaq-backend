from pydantic import BaseModel, Field
from typing import Optional, List
from uuid import UUID
from datetime import datetime
from decimal import Decimal
from schemas.media import AssetImageResponse, AssetImageCreate

class PropertyBase(BaseModel):
    title: str
    description: Optional[str] = None
    price: Decimal
    location: str
    listing_type: str = "sale"


class PropertyResponse(PropertyBase):
    id: UUID
    seller_id: UUID
    status: str
    images: List[AssetImageResponse] = []
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class PropertyCreate(PropertyBase):
    images: Optional[List[AssetImageCreate]] = None

class PropertyUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    price: Optional[Decimal] = None
    location: Optional[str] = None
    listing_type: Optional[str] = None
    status: Optional[str] = None
    images: Optional[List[AssetImageCreate]] = None

class PropertyAgreementResponse(BaseModel):
    id: UUID
    user_id: UUID
    property_id: UUID
    
    total_price: Decimal
    deposit_paid: Decimal
    remaining_balance: Decimal
    
    plan_type: str
    duration_months: Optional[int] = None
    monthly_installment: Optional[Decimal] = None
    next_due_date: Optional[datetime] = None
    status: str
    
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
