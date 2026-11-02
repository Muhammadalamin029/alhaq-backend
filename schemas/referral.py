from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, Field, validator


class ReferralCampaignCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=255)
    description: Optional[str] = Field(None, max_length=5000)
    required_referrals: int = Field(..., ge=1, le=1000)
    start_at: datetime
    end_at: datetime
    customer_pays_delivery: bool = False
    max_credited_referrals_per_device: int = Field(1, ge=1, le=50)
    product_ids: List[UUID] = Field(default_factory=list)

    @validator("end_at")
    def end_after_start(cls, v, values):
        start = values.get("start_at")
        if start and v <= start:
            raise ValueError("End date must be after the start date")
        return v

    @validator("product_ids")
    def at_least_one_product(cls, v):
        if not v:
            raise ValueError("Select at least one reward product")
        if len(set(v)) != len(v):
            raise ValueError("Duplicate reward products are not allowed")
        return v


class ReferralCampaignUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=2, max_length=255)
    description: Optional[str] = Field(None, max_length=5000)
    required_referrals: Optional[int] = Field(None, ge=1, le=1000)
    start_at: Optional[datetime] = None
    end_at: Optional[datetime] = None
    customer_pays_delivery: Optional[bool] = None
    max_credited_referrals_per_device: Optional[int] = Field(None, ge=1, le=50)
    product_ids: Optional[List[UUID]] = None

    @validator("product_ids")
    def no_duplicates(cls, v):
        if v is not None:
            if not v:
                raise ValueError("Select at least one reward product")
            if len(set(v)) != len(v):
                raise ValueError("Duplicate reward products are not allowed")
        return v


class ReferralOrderCreate(BaseModel):
    address_id: UUID


class ReferralReasonRequest(BaseModel):
    reason: Optional[str] = Field(None, max_length=255)
