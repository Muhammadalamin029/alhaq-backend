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

class SessionRequestCreate(BaseModel):
    title: str
    location: str
    proposed_price: Decimal
    description: Optional[str] = None
    property_details: Optional[str] = None
    buildings_count: Optional[int] = 1
    images: Optional[List[AssetImageCreate]] = None
    units: Optional[List[PropertyUnitCreate]] = None

class SessionRequestResponse(BaseModel):
    id: UUID
    user_id: UUID
    title: Optional[str] = None
    location: str
    description: Optional[str] = None
    proposed_price: Optional[Decimal] = None
    property_details: Optional[str] = None
    buildings_count: Optional[int] = 1
    admin_notes: Optional[str] = None  # alias for property_details sent to frontend
    status: str
    images: List[AssetImageResponse] = []
    units: List[PropertyUnitResponse] = []
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

    @classmethod
    def model_validate(cls, obj, *args, **kwargs):
        instance = super().model_validate(obj, *args, **kwargs)
        # Expose property_details as admin_notes for frontend compatibility
        if instance.admin_notes is None and hasattr(obj, 'property_details'):
            instance.admin_notes = obj.property_details
        
        # Map units_data from DB to units field if present
        if hasattr(obj, 'units_data') and obj.units_data:
            instance.units = obj.units_data
            
        return instance
class PropertyPublish(BaseModel):
    new_price: Decimal
