from pydantic import BaseModel, Field
from typing import Optional, List
from uuid import UUID
from datetime import datetime
from decimal import Decimal

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

class CarUnitResponse(CarUnitBase):
    id: UUID
    car_id: UUID
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class CarCreate(CarBase):
    units: List[CarUnitCreate] # Initial stock units

class CarUpdate(BaseModel):
    brand: Optional[str] = None
    model: Optional[str] = None
    year: Optional[int] = None
    price: Optional[Decimal] = None
    min_deposit_percentage: Optional[Decimal] = None
    status: Optional[str] = None

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

class CarInspectionResponse(CarInspectionBase):
    id: UUID
    user_id: UUID
    car_id: UUID
    unit_id: Optional[UUID] = None
    created_at: datetime

    class Config:
        from_attributes = True

class CarResponse(CarBase):
    id: UUID
    seller_id: UUID
    status: str
    units: List[CarUnitResponse] = []
    created_at: datetime
    updated_at: datetime
    inspections: List[CarInspectionResponse] = []

    class Config:
        from_attributes = True
