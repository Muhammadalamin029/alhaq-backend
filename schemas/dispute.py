from pydantic import BaseModel, Field
from typing import Optional, Any
from datetime import datetime
from uuid import UUID

class DisputeCreate(BaseModel):
    title: str
    reason: str
    order_id: Optional[UUID] = None
    agreement_id: Optional[UUID] = None

class DisputeUpdate(BaseModel):
    status: Optional[str] = None
    resolution_notes: Optional[str] = None

class DisputeResponse(BaseModel):
    id: UUID
    user_id: UUID
    order_id: Optional[UUID] = None
    agreement_id: Optional[UUID] = None
    title: str
    reason: str
    status: str
    resolution_notes: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class DisputeListResponse(BaseModel):
    success: bool
    message: str
    data: list[DisputeResponse]

class DisputeSingleResponse(BaseModel):
    success: bool
    message: str
    data: DisputeResponse
