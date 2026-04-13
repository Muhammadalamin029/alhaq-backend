from pydantic import BaseModel, Field
from typing import Optional, List
from uuid import UUID
from datetime import datetime
from decimal import Decimal
from schemas.media import AssetImageResponse, AssetImageCreate

class PhoneBase(BaseModel):
    brand: str
    model: str
    specs: Optional[str] = None
    price: Decimal
    min_deposit_percentage: Optional[Decimal] = 10.0

class PhoneUnitBase(BaseModel):
    imei: str
    color: Optional[str] = None
    grade: Optional[str] = None
    battery_health: Optional[int] = None
    status: str = "available"

class PhoneUnitCreate(PhoneUnitBase):
    pass

class PhoneUnitUpdate(BaseModel):
    imei: Optional[str] = None
    color: Optional[str] = None
    grade: Optional[str] = None
    battery_health: Optional[int] = None
    status: Optional[str] = None

class PhoneUnitResponse(PhoneUnitBase):
    id: UUID
    phone_id: UUID
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class PhoneCreate(PhoneBase):
    units: List[PhoneUnitCreate]
    images: Optional[List[AssetImageCreate]] = None

class PhoneUpdate(BaseModel):
    brand: Optional[str] = None
    model: Optional[str] = None
    specs: Optional[str] = None
    price: Optional[Decimal] = None
    min_deposit_percentage: Optional[Decimal] = None
    status: Optional[str] = None
    images: Optional[List[AssetImageCreate]] = None

class PhoneResponse(PhoneBase):
    id: UUID
    seller_id: UUID
    status: str
    units: List[PhoneUnitResponse] = []
    images: List[AssetImageResponse] = []
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class PhoneInspectionBase(BaseModel):
    inspection_date: datetime
    notes: Optional[str] = None
    agreed_price: Optional[Decimal] = None
    status: str = "scheduled"

class PhoneInspectionSchedule(BaseModel):
    phone_id: UUID
    unit_id: Optional[UUID] = None
    inspection_date: datetime

class PhoneInspectionResponse(PhoneInspectionBase):
    id: UUID
    user_id: UUID
    phone_id: UUID
    unit_id: Optional[UUID] = None
    created_at: datetime
    
    phone: Optional[PhoneResponse] = None

    class Config:
        from_attributes = True

class PhoneAgreementResponse(BaseModel):
    id: UUID
    user_id: UUID
    phone_id: UUID
    unit_id: Optional[UUID] = None
    inspection_id: Optional[UUID] = None
    
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

class PhonePaymentResponse(BaseModel):
    id: UUID
    agreement_id: UUID
    user_id: UUID
    amount: Decimal
    paystack_ref: str
    payment_type: str
    status: str
    created_at: datetime

    class Config:
        from_attributes = True
