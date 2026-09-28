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
    payment_method: str = Field(default="flutterwave", description="Payment method: flutterwave")


class CardChargeRequest(BaseModel):
    """Step 1 of the Direct-API card flow. Raw card fields are transmitted over
    TLS straight to Flutterwave and are never persisted server-side."""

    order_id: Optional[UUID] = None
    agreement_id: Optional[UUID] = None
    category: str = Field("order", pattern="^(order|asset_deposit|asset_installment|full_pay)$")
    amount: float = Field(..., gt=0, description="Amount in Naira (NGN)")
    email: str = Field(..., description="Customer email")
    fullname: Optional[str] = Field(None, description="Cardholder full name")
    phone_number: Optional[str] = None
    card_number: str = Field(..., description="Card PAN (digits, spaces allowed)")
    cvv: str = Field(..., description="Card CVV")
    expiry_month: str = Field(..., description="2-digit expiry month")
    expiry_year: str = Field(..., description="2- or 4-digit expiry year")
    redirect_url: Optional[str] = Field(None, description="Return URL for 3DS redirect authentication")
    metadata: Optional[Dict[str, Any]] = None
    payment_method: str = Field(default="flutterwave", description="Payment method: flutterwave")


class CardAuthorizeRequest(BaseModel):
    """Step 2: resubmit the full card payload with PIN/AVS authorization."""

    tx_ref: str = Field(..., description="Transaction reference returned by charge-card")
    card_number: str = Field(..., description="Card PAN (digits, spaces allowed)")
    cvv: str = Field(..., description="Card CVV")
    expiry_month: str = Field(..., description="2-digit expiry month")
    expiry_year: str = Field(..., description="2- or 4-digit expiry year")
    authorization: Dict[str, Any] = Field(..., description='e.g. {"mode": "pin", "pin": "3310"} or {"mode": "avs_noauth", ...address fields}')
    email: Optional[str] = None
    fullname: Optional[str] = None
    phone_number: Optional[str] = None
    redirect_url: Optional[str] = None


class CardValidateRequest(BaseModel):
    """Step 3: validate the charge with the OTP sent to the customer."""

    tx_ref: str = Field(..., description="Transaction reference returned by charge-card")
    otp: str = Field(..., description="OTP sent to the customer")

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
    fullname: Optional[str] = None
    phone_number: Optional[str] = None
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
    reference: str = Field(..., description="Our transaction reference (tx_ref)")
    transaction_id: Optional[int] = Field(None, description="Flutterwave transaction id (from redirect/webhook)")

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
    buyer_name: Optional[str] = None
    buyer_email: Optional[str] = None
    receipt_number: Optional[str] = None
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

class ReceiptParty(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None

class ReceiptResponse(BaseModel):
    receipt_number: str
    issued_at: datetime
    currency: str
    amount: Decimal
    amount_display: str
    status: str
    reference: Optional[str] = None
    transaction_id: Optional[str] = None
    payment_method: Optional[str] = None
    payment_category: str
    payment_type: Optional[str] = None
    purpose: str
    paid_at: Optional[datetime] = None
    payer: ReceiptParty
    payee: ReceiptParty
    order: Optional[Dict[str, Any]] = None
    agreement: Optional[Dict[str, Any]] = None
