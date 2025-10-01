from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from decimal import Decimal
from datetime import datetime

class SellerPayoutBase(BaseModel):
    amount: Decimal = Field(..., description="Payout amount")
    account_number: str = Field(..., description="Bank account number")
    bank_code: str = Field(..., description="Bank code")
    bank_name: str = Field(..., description="Bank name")

class SellerPayoutCreate(SellerPayoutBase):
    pass

class SellerPayoutResponse(BaseModel):
    id: str
    seller_id: str
    amount: Decimal
    platform_fee: Decimal
    net_amount: Decimal
    status: str
    transfer_reference: Optional[str] = None
    paystack_transfer_id: Optional[str] = None
    account_number: Optional[str] = None
    bank_code: Optional[str] = None
    bank_name: Optional[str] = None
    processed_at: Optional[datetime] = None
    failure_reason: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class SellerPayoutListResponse(BaseModel):
    success: bool
    message: str
    data: List[SellerPayoutResponse]
    pagination: Dict[str, Any]

class SellerBalanceResponse(BaseModel):
    success: bool
    message: str
    data: Dict[str, Any]

class SellerBalanceData(BaseModel):
    available_balance: Decimal
    pending_balance: Decimal
    total_paid: Decimal
    total_revenue: Decimal
    platform_fee_rate: Decimal
    payout_account_configured: bool

class PayoutRequestResponse(BaseModel):
    success: bool
    message: str
    data: SellerPayoutResponse

class AdminPayoutListResponse(BaseModel):
    success: bool
    message: str
    data: List[SellerPayoutResponse]
    pagination: Dict[str, Any]

class PayoutProcessRequest(BaseModel):
    payout_id: str = Field(..., description="Payout ID to process")

class PayoutProcessResponse(BaseModel):
    success: bool
    message: str
    data: Dict[str, Any]
