from pydantic import BaseModel, Field
from typing import Optional, List
from uuid import UUID
from datetime import datetime
from decimal import Decimal
from schemas.media import AssetImageResponse, AssetImageCreate

class SellerSummary(BaseModel):
    id: UUID
    business_name: str
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None

    class Config:
        from_attributes = True

class PropertyUnitResponse(BaseModel):
    id: UUID
    property_id: UUID
    unit_name: Optional[str] = None
    unit_number: Optional[str] = None
    status: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class PropertyBase(BaseModel):
    title: str
    description: Optional[str] = None
    price: Decimal
    location: str
    listing_type: str = "sale"
    buildings_count: Optional[int] = 1


class PropertyResponse(PropertyBase):
    id: UUID
    seller_id: UUID
    status: str
    images: List[AssetImageResponse] = []
    units: List[PropertyUnitResponse] = []
    seller: Optional[SellerSummary] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class PropertyUnitCreate(BaseModel):
    unit_name: Optional[str] = None
    unit_number: Optional[str] = None

class PropertyCreate(PropertyBase):
    images: Optional[List[AssetImageCreate]] = None
    units: Optional[List[PropertyUnitCreate]] = None

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

class PropertyPublish(BaseModel):
    new_price: Decimal
