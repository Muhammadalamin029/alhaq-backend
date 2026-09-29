from pydantic import BaseModel, Field, EmailStr, field_validator
from typing import Optional, List
from datetime import datetime
from uuid import UUID
from decimal import Decimal


ALLOWED_CHANNELS = ("cash", "bank_transfer", "pos")


class ExternalItemIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    quantity: int = Field(..., gt=0, le=10000)
    unit_price: float = Field(..., gt=0, le=1_000_000_000)
    description: Optional[str] = Field(None, max_length=2000)


class ExternalPaymentCreate(BaseModel):
    payer_name: str = Field(..., min_length=1, max_length=255)
    payer_email: EmailStr
    payer_phone: Optional[str] = Field(None, max_length=50)
    items: List[ExternalItemIn] = Field(..., min_length=1, max_length=50)
    channel: str = Field(..., pattern="^(cash|bank_transfer|pos)$")
    notes: Optional[str] = Field(None, max_length=2000)
    paid_at: Optional[datetime] = None
    send_receipt: bool = False

    @field_validator("payer_name")
    @classmethod
    def _strip_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("payer_name is required")
        return v


class ExternalPaymentPdfUpload(BaseModel):
    pdf_url: str = Field(..., min_length=10, max_length=2000,
                         description="Cloudinary secure_url of the receipt PDF")
    send_receipt: bool = True
    to_email_override: Optional[EmailStr] = None

    @field_validator("pdf_url")
    @classmethod
    def _must_be_cloudinary_pdf(cls, v: str) -> str:
        v = v.strip()
        if not v.startswith("https://"):
            raise ValueError("pdf_url must be https")
        host_ok = ("res.cloudinary.com" in v) or ("cloudinary.com" in v)
        if not host_ok:
            raise ValueError("pdf_url must be a Cloudinary URL")
        return v


class ExternalPaymentItemOut(BaseModel):
    id: UUID
    name: str
    description: Optional[str] = None
    quantity: int
    unit_price: Decimal

    class Config:
        from_attributes = True


class ExternalPaymentOut(BaseModel):
    id: UUID
    receipt_number: str
    payer_name: str
    payer_email: str
    payer_phone: Optional[str] = None
    buyer_id: Optional[UUID] = None
    amount: Decimal
    channel: str
    status: str
    notes: Optional[str] = None
    paid_at: Optional[datetime] = None
    recorded_by: UUID
    pdf_url: Optional[str] = None
    created_at: Optional[datetime] = None
    items: List[ExternalPaymentItemOut] = []

    class Config:
        from_attributes = True


class ExternalPaymentCreateResponse(BaseModel):
    success: bool = True
    message: str = "External payment recorded"
    data: ExternalPaymentOut
