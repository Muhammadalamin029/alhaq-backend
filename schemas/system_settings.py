from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


class SystemSettingsGeneral(BaseModel):
    site_name: str
    site_description: Optional[str] = None
    contact_email: Optional[str] = None
    support_email: Optional[str] = None
    currency: str
    language: str
    timezone: str


class SystemSettingsPayments(BaseModel):
    commission_rate_percent: float
    minimum_payout_amount: float
    payout_schedule: str


class SystemSettingsInspection(BaseModel):
    minimum_inspection_notice_hours: int
    inspection_cancellation_cutoff_hours: int
    missed_inspection_expiry_hours: int


class SystemSettingsSecurity(BaseModel):
    require_email_verification: bool
    require_seller_kyc: bool
    access_token_lifetime_minutes: int
    max_login_attempts: int
    lockout_duration_minutes: int


class SystemSettingsNotifications(BaseModel):
    new_user_notifications: bool
    new_seller_notifications: bool
    dispute_notifications: bool
    system_alerts: bool
    weekly_reports: bool


class SystemSettingsMeta(BaseModel):
    scope: str
    updated_at: Optional[datetime] = None
    updated_by_user_id: Optional[UUID] = None


class SystemSettingsResponse(BaseModel):
    general: SystemSettingsGeneral
    payments: SystemSettingsPayments
    inspection: SystemSettingsInspection
    security: SystemSettingsSecurity
    notifications: SystemSettingsNotifications
    meta: SystemSettingsMeta


class UpdateSystemSettingsGeneralRequest(BaseModel):
    site_name: str = Field(..., min_length=1, max_length=255)
    site_description: Optional[str] = Field(None, max_length=2000)
    contact_email: Optional[EmailStr] = None
    support_email: Optional[EmailStr] = None
    currency: str = Field(..., min_length=3, max_length=10)
    language: str = Field(..., min_length=2, max_length=10)
    timezone: str = Field(..., min_length=1, max_length=100)


class UpdateSystemSettingsPaymentsRequest(BaseModel):
    commission_rate_percent: float = Field(..., ge=0, le=100)
    minimum_payout_amount: float = Field(..., ge=0)
    payout_schedule: str = Field(..., pattern="^(daily|weekly|monthly)$")


class UpdateSystemSettingsInspectionRequest(BaseModel):
    minimum_inspection_notice_hours: int = Field(..., ge=1, le=720)
    inspection_cancellation_cutoff_hours: int = Field(..., ge=0, le=720)
    missed_inspection_expiry_hours: int = Field(..., ge=1, le=720)


class UpdateSystemSettingsSecurityRequest(BaseModel):
    require_email_verification: bool
    require_seller_kyc: bool
    access_token_lifetime_minutes: int = Field(..., ge=5, le=1440)
    max_login_attempts: int = Field(..., ge=1, le=20)
    lockout_duration_minutes: int = Field(..., ge=1, le=1440)


class UpdateSystemSettingsNotificationsRequest(BaseModel):
    new_user_notifications: bool
    new_seller_notifications: bool
    dispute_notifications: bool
    system_alerts: bool
    weekly_reports: bool
