from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
from decimal import Decimal
from datetime import datetime
from uuid import UUID

class PaymentInitializeRequest(BaseModel):
    order_id: Optional[UUID] = None
    agreement_id: Optional[UUID] = None
    category: str = Field("order", pattern="^(order|asset_deposit|asset_installment|full_pay)$")
    amount: float = Field(..., gt=0, description="Amount in Naira (NGN)")
    email: str = Field(..., description="Customer email")
    callback_url: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    payment_method: str = Field(default="paystack", description="Payment method: paystack")

class PaymentInitializeResponse(BaseModel):
    success: bool
    message: str
    data: Dict[str, Any]

class BankTransferInitializeRequest(BaseModel):
    order_id: Optional[UUID] = None
    agreement_id: Optional[UUID] = None
    category: str = Field("order", pattern="^(order|asset_deposit|asset_installment|full_pay)$")
    amount: float = Field(..., gt=0, description="Amount in Naira (NGN)")
    email: str = Field(..., description="Customer email")
    metadata: Optional[Dict[str, Any]] = None

class BankTransferDetails(BaseModel):
    account_number: str
    account_name: str
    bank_name: str
    amount: Decimal
    reference: str
    expires_at: Optional[str] = None
    currency: str = "NGN"

class BankTransferInitializeResponse(BaseModel):
    success: bool
    message: str
    data: BankTransferDetails

class PaymentVerifyRequest(BaseModel):
    reference: str = Field(..., description="Paystack transaction reference")

class PaymentVerifyResponse(BaseModel):
    success: bool
    message: str
    data: Dict[str, Any]

class PaymentWebhookData(BaseModel):
    event: str
    data: Dict[str, Any]

class BankResponse(BaseModel):
    success: bool
    message: str
    data: list

class PaymentResponse(BaseModel):
    id: UUID
    order_id: Optional[UUID] = None
    agreement_id: Optional[UUID] = None
    buyer_id: UUID
    seller_id: Optional[UUID] = None
    seller_name: Optional[str] = None
    amount: Decimal
    status: str
    payment_category: str
    payment_type: Optional[str] = None
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
