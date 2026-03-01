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

    class Config:
        from_attributes = True

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

class CarResponse(CarBase):
    id: UUID
    seller_id: UUID
    status: str
    units: List[CarUnitResponse] = []
    images: List[AssetImageResponse] = []
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
