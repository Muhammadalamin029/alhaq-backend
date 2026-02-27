from pydantic import BaseModel
from uuid import UUID
from datetime import datetime
from typing import Optional

class AssetImageResponse(BaseModel):
    id: UUID
    image_url: str
    product_id: Optional[UUID] = None
    car_id: Optional[UUID] = None
    property_id: Optional[UUID] = None
    phone_id: Optional[UUID] = None
    created_at: datetime

    class Config:
        from_attributes = True

class AssetImageCreate(BaseModel):
    image_url: str
