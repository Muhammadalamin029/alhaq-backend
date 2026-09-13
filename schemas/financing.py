from pydantic import BaseModel, Field
from typing import Optional, List
from uuid import UUID
from datetime import datetime
from decimal import Decimal


class UserMini(BaseModel):
    id: UUID
    email: str
    name: Optional[str] = None

    class Config:
        from_attributes = True


# ---------------- Document Requirements ----------------

class FinancingDocumentRequirementOut(BaseModel):
    id: UUID
    name: str
    description: Optional[str] = None
    is_required: bool
    is_active: bool
    display_order: int
    created_at: datetime

    class Config:
        from_attributes = True


class FinancingDocumentRequirementCreate(BaseModel):
    name: str
    description: Optional[str] = None
    is_required: bool = True
    display_order: int = 0


class FinancingDocumentRequirementUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    is_required: Optional[bool] = None
    display_order: Optional[int] = None


class FinancingDocumentRequirementStatus(BaseModel):
    is_active: bool


# ---------------- Applications ----------------

class FinancingApplicationDocumentIn(BaseModel):
    requirement_id: UUID
    document_url: str
    original_filename: Optional[str] = None


class FinancingApplicationDocumentOut(BaseModel):
    id: UUID
    requirement_id: UUID
    document_url: str
    original_filename: Optional[str] = None
    requirement: Optional[FinancingDocumentRequirementOut] = None

    class Config:
        from_attributes = True


class FinancingApplicationSubmit(BaseModel):
    employment_status: str = Field(
        ..., pattern="^(employed|self_employed|business_owner|unemployed|retired|student)$"
    )
    employer_name: Optional[str] = None
    job_title: Optional[str] = None
    monthly_income: Decimal
    employment_duration_months: Optional[int] = None
    additional_notes: Optional[str] = None
    documents: List[FinancingApplicationDocumentIn] = []


class FinancingApplicationOut(BaseModel):
    id: UUID
    user_id: UUID
    employment_status: str
    employer_name: Optional[str] = None
    job_title: Optional[str] = None
    monthly_income: Decimal
    employment_duration_months: Optional[int] = None
    additional_notes: Optional[str] = None
    status: str
    decision_reason: Optional[str] = None
    revocation_reason: Optional[str] = None
    reviewed_at: Optional[datetime] = None
    revoked_at: Optional[datetime] = None
    created_at: datetime

    documents: List[FinancingApplicationDocumentOut] = []
    user: Optional[UserMini] = None

    class Config:
        from_attributes = True


class FinancingApplicationDecision(BaseModel):
    reason: Optional[str] = None
