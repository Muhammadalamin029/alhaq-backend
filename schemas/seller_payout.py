from pydantic import BaseModel, Field, field_validator
from typing import Optional, Dict, Any
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
    amount: Decimal
    platform_fee: Decimal
    net_amount: Decimal
    status: str
    transfer_reference: Optional[str] = None
    account_number: Optional[str] = None
    bank_code: Optional[str] = None
    bank_name: Optional[str] = None
    created_at: datetime
    processed_at: Optional[datetime] = None
    failure_reason: Optional[str] = None

    class Config:
        from_attributes = True
        
    @field_validator('id', mode='before')
    @classmethod
    def convert_uuid_to_str(cls, v):
        """Convert UUID to string if needed"""
        if hasattr(v, '__str__'):
            return str(v)
        return v

class AdminPayoutResponse(BaseModel):
    id: str
    amount: Decimal
    platform_fee: Decimal
    net_amount: Decimal
    status: str
    transfer_reference: Optional[str] = None
    account_number: Optional[str] = None
    bank_code: Optional[str] = None
    bank_name: Optional[str] = None
    created_at: datetime
    processed_at: Optional[datetime] = None
    failure_reason: Optional[str] = None
    seller: Optional[Dict[str, Any]] = None

    class Config:
        from_attributes = True
        
    @field_validator('id', mode='before')
    @classmethod
    def convert_uuid_to_str(cls, v):
        """Convert UUID to string if needed"""
        if hasattr(v, '__str__'):
            return str(v)
        return v

class SellerPayoutListResponse(BaseModel):
    success: bool
    message: str
    data: list[SellerPayoutResponse]
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
    platform_fee_rate: float
    payout_account_configured: bool

class PayoutRequestResponse(BaseModel):
    success: bool
    message: str
    data: SellerPayoutResponse

# New schemas for payout account configuration
class PayoutAccountConfig(BaseModel):
    account_number: str = Field(..., min_length=10, max_length=20, description="Bank account number")
    bank_code: str = Field(..., min_length=3, max_length=10, description="Bank code")
    bank_name: str = Field(..., min_length=2, max_length=100, description="Bank name")

class PayoutAccountData(BaseModel):
    account_number: Optional[str] = None
    bank_code: Optional[str] = None
    bank_name: Optional[str] = None

class PayoutAccountResponse(BaseModel):
    success: bool
    message: str
    data: Optional[PayoutAccountData] = None

class PayoutAccountVerifyRequest(BaseModel):
    account_number: str = Field(..., description="Account number to verify")
    bank_code: str = Field(..., description="Bank code for verification")

class PayoutAccountVerifyResponse(BaseModel):
    success: bool
    message: str
    data: Dict[str, Any]

# Admin payout schemas
class AdminPayoutListResponse(BaseModel):
    success: bool
    message: str
    data: list[AdminPayoutResponse]
    pagination: Dict[str, Any]

class PayoutProcessRequest(BaseModel):
    payout_id: str
    action: str  # "approve" or "reject"
    notes: Optional[str] = None

class PayoutProcessResponse(BaseModel):
    success: bool
    message: str
    data: Optional[SellerPayoutResponse] = None