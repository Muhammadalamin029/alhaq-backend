from pydantic import BaseModel, Field
from typing import Optional, List
from uuid import UUID
from datetime import datetime
from decimal import Decimal

class AssetInspectionBase(BaseModel):
    asset_type: str = Field(..., pattern="^(automotive|property|phone)$")
    asset_id: UUID
    unit_id: Optional[UUID] = None
    inspection_date: datetime
    notes: Optional[str] = None
    agreed_price: Optional[Decimal] = None
    status: str = "scheduled"

class AssetInspectionSchedule(BaseModel):
    asset_type: str = Field(..., pattern="^(automotive|property|phone)$")
    asset_id: UUID
    unit_id: Optional[UUID] = None
    inspection_date: datetime

class AssetInspectionReview(BaseModel):
    inspection_date: Optional[datetime] = None
    action: str = Field(..., pattern="^(approve|reject)$")

class AssetInspectionComplete(BaseModel):
    notes: Optional[str] = None
    agreed_price: Decimal
    plan_type: str = Field(..., pattern="^(structured|flexible)$")
    duration_months: Optional[int] = None
    monthly_installment: Optional[Decimal] = None
    unit_id: Optional[UUID] = None

class AssetMini(BaseModel):
    id: UUID
    type: str
    title: str # Brand + Model or Property Title
    price: Decimal
    image_url: Optional[str] = None

    class Config:
        from_attributes = True

class UserMini(BaseModel):
    id: UUID
    email: str
    name: Optional[str] = None
    
    class Config:
        from_attributes = True

class AssetInspectionResponse(BaseModel):
    id: UUID
    asset_type: str
    asset_id: UUID
    unit_id: Optional[UUID] = None
    user_id: UUID
    seller_id: UUID
    inspection_date: datetime
    notes: Optional[str] = None
    agreed_price: Optional[Decimal] = None
    status: str
    created_at: datetime
    
    # Optional nested data
    asset: Optional[AssetMini] = None
    user: Optional[UserMini] = None

    class Config:
        from_attributes = True

class AssetAgreementBase(BaseModel):
    asset_type: str
    asset_id: UUID
    unit_id: Optional[UUID] = None
    inspection_id: Optional[UUID] = None
    total_price: Decimal
    deposit_paid: Optional[Decimal] = 0
    remaining_balance: Optional[Decimal] = None
    plan_type: str = Field(..., pattern="^(structured|flexible)$")
    duration_months: Optional[int] = None
    monthly_installment: Optional[Decimal] = None
    status: str = "pending_review"

class AssetAgreementResponse(AssetAgreementBase):
    id: UUID
    seller_id: UUID
    user_id: UUID
    next_due_date: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    
    asset: Optional[AssetMini] = None

    class Config:
        from_attributes = True

class AssetPaymentResponse(BaseModel):
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

class AgreementPaymentInitialize(BaseModel):
    amount: Decimal
    email: str

class AgreementPaymentVerify(BaseModel):
    reference: str
