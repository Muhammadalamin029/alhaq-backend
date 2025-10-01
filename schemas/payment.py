from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
from decimal import Decimal
from datetime import datetime
from uuid import UUID

class PaymentInitializeRequest(BaseModel):
    order_id: str
    amount: int = Field(..., gt=0, description="Amount in kobo (NGN)")
    email: str = Field(..., description="Customer email")
    metadata: Optional[Dict[str, Any]] = None

class PaymentInitializeResponse(BaseModel):
    success: bool
    message: str
    data: Dict[str, Any]

class PaymentVerifyRequest(BaseModel):
    reference: str = Field(..., description="Paystack transaction reference")

class PaymentVerifyResponse(BaseModel):
    success: bool
    message: str
    data: Dict[str, Any]

class PaymentWebhookData(BaseModel):
    event: str
    data: Dict[str, Any]

class TransferRecipientRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=255)
    account_number: str = Field(..., min_length=10, max_length=10)
    bank_code: str = Field(..., min_length=3, max_length=3)
    email: str = Field(..., description="Seller email")

class TransferRecipientResponse(BaseModel):
    success: bool
    message: str
    data: Dict[str, Any]

class TransferRequest(BaseModel):
    amount: int = Field(..., gt=0, description="Amount in kobo (NGN)")
    recipient_code: str = Field(..., description="Paystack recipient code")
    reference: str = Field(..., description="Transfer reference")
    reason: str = Field(default="Seller payout", max_length=255)

class TransferResponse(BaseModel):
    success: bool
    message: str
    data: Dict[str, Any]

class BankResponse(BaseModel):
    success: bool
    message: str
    data: list

class PaymentResponse(BaseModel):
    id: UUID
    order_id: UUID
    buyer_id: UUID
    seller_id: UUID
    amount: Decimal
    status: str
    payment_method: str
    transaction_id: str
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True

class PaymentListResponse(BaseModel):
    success: bool
    message: str
    data: list[PaymentResponse]
    pagination: Dict[str, Any]
