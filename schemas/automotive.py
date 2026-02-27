from pydantic import BaseModel, Field
from typing import Optional, List
from uuid import UUID
from datetime import datetime
from decimal import Decimal
from schemas.media import AssetImageResponse, AssetImageCreate

class CarBase(BaseModel):
    brand: str
    model: str
    year: int
    price: Decimal
    min_deposit_percentage: Optional[Decimal] = 10.0

class CarUnitBase(BaseModel):
    vin: str
    mileage: int
    color: Optional[str] = None
    status: str = "available"

class CarUnitCreate(CarUnitBase):
    pass

class CarUnitUpdate(BaseModel):
    vin: Optional[str] = None
    mileage: Optional[int] = None
    color: Optional[str] = None
    status: Optional[str] = None

class CarUnitResponse(CarUnitBase):
    id: UUID
    car_id: UUID
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class CarCreate(CarBase):
    units: List[CarUnitCreate] # Initial stock units
    images: Optional[List[AssetImageCreate]] = None

class CarUpdate(BaseModel):
    brand: Optional[str] = None
    model: Optional[str] = None
    year: Optional[int] = None
    price: Optional[Decimal] = None
    min_deposit_percentage: Optional[Decimal] = None
    status: Optional[str] = None
    images: Optional[List[AssetImageCreate]] = None

class CarInspectionBase(BaseModel):
    inspection_date: datetime
    notes: Optional[str] = None
    agreed_price: Optional[Decimal] = None
    status: Optional[str] = "scheduled"

class CarInspectionSchedule(BaseModel):
    car_id: UUID
    unit_id: Optional[UUID] = None # Customer can pick a specific physical car
    inspection_date: datetime

class CarInspectionComplete(BaseModel):
    notes: Optional[str] = None
    agreed_price: Decimal

class UserMini(BaseModel):
    id: UUID
    email: str
    
    class Config:
        from_attributes = True

class ProfileMini(BaseModel):
    id: UUID
    name: str
    phone: Optional[str] = None
    
    class Config:
        from_attributes = True

class CarMini(BaseModel):
    id: UUID
    brand: str
    model: str
    year: int
    price: Decimal
    
    class Config:
        from_attributes = True

class CarInspectionResponse(CarInspectionBase):
    id: UUID
    user_id: UUID
    car_id: UUID
    unit_id: Optional[UUID] = None
    created_at: datetime
    
    # Nested details for listings
    car: Optional[CarMini] = None
    unit: Optional[CarUnitBase] = None
    user: Optional[UserMini] = None # Or Profile info

    class Config:
        from_attributes = True

class CarResponse(CarBase):
    id: UUID
    seller_id: UUID
    status: str
    units: List[CarUnitResponse] = []
    images: List[AssetImageResponse] = []
    created_at: datetime
    updated_at: datetime
    inspections: List[CarInspectionResponse] = []

    class Config:
        from_attributes = True

class CarPaymentResponse(BaseModel):
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

class CarAgreementResponse(BaseModel):
    id: UUID
    user_id: UUID
    car_id: UUID
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

    # Nested info
    car: Optional[CarMini] = None
    unit: Optional[CarUnitBase] = None
    payments: List[CarPaymentResponse] = []

    class Config:
        from_attributes = True

class CarAgreementUpdate(BaseModel):
    plan_type: Optional[str] = None
    duration_months: Optional[int] = None
    monthly_installment: Optional[Decimal] = None
    status: Optional[str] = None
