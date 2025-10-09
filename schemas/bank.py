"""
Bank schemas for Paystack bank data
"""

from pydantic import BaseModel, Field
from typing import List, Optional

class BankData(BaseModel):
    """Individual bank data from Paystack"""
    id: int
    name: str
    slug: str
    code: str
    longcode: Optional[str] = None
    gateway: Optional[str] = None
    pay_with_bank: bool = False
    active: bool = True
    is_deleted: bool = False
    country: str = "Nigeria"
    currency: str = "NGN"
    type: str = "nuban"

class BankListResponse(BaseModel):
    """Response for bank list API"""
    success: bool
    message: str
    data: List[BankData]
    total: int

class BankSearchRequest(BaseModel):
    """Request for bank search"""
    query: str = Field(..., min_length=1, max_length=100, description="Search query for bank name or code")

class BankSearchResponse(BaseModel):
    """Response for bank search API"""
    success: bool
    message: str
    data: List[BankData]
    total: int
