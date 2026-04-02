from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, Optional

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from core.config import settings as app_settings
from core.model import SellerProfile, SystemSettings, User
from core.notifications_service import create_notification
from schemas.system_settings import SystemSettingsResponse


class SystemSettingsService:
    DEFAULT_SCOPE = "default"

    def _build_defaults(self) -> Dict[str, Any]:
        support_email = app_settings.FROM_EMAIL or None
        marketplace_copy = (
            "Secure escrow marketplace for verified real estate, automotive, "
            "and luxury retail assets."
        )
        return {
            "scope": self.DEFAULT_SCOPE,
            "site_name": "Alhaq",
            "site_description": marketplace_copy,
            "contact_email": support_email,
            "support_email": support_email,
            "currency": "NGN",
            "language": "en",
            "timezone": "Africa/Lagos",
            "commission_rate_percent": Decimal("5.00"),
            "minimum_payout_amount": Decimal("10000.00"),
            "payout_schedule": "weekly",
            "minimum_inspection_notice_hours": 24,
            "inspection_cancellation_cutoff_hours": 12,
            "missed_inspection_expiry_hours": 24,
            "require_email_verification": True,
            "require_seller_kyc": True,
            "access_token_lifetime_minutes": 30,
            "max_login_attempts": 5,
            "lockout_duration_minutes": 15,
            "new_user_notifications": True,
            "new_seller_notifications": True,
            "dispute_notifications": True,
            "system_alerts": True,
            "weekly_reports": True,
        }

    def get_or_create_settings(self, db: Session) -> SystemSettings:
        settings_row = (
            db.query(SystemSettings)
            .filter(SystemSettings.scope == self.DEFAULT_SCOPE)
            .first()
        )
        if settings_row:
            return settings_row

        settings_row = SystemSettings(**self._build_defaults())
        db.add(settings_row)
        db.commit()
        db.refresh(settings_row)
        return settings_row

    def get_settings(self, db: Session) -> SystemSettingsResponse:
        return self.to_response(self.get_or_create_settings(db))

    def to_response(self, settings_row: SystemSettings) -> SystemSettingsResponse:
        return SystemSettingsResponse.model_validate({
            "general": {
                "site_name": settings_row.site_name,
                "site_description": settings_row.site_description,
                "contact_email": settings_row.contact_email,
                "support_email": settings_row.support_email,
                "currency": settings_row.currency,
                "language": settings_row.language,
                "timezone": settings_row.timezone,
            },
            "payments": {
                "commission_rate_percent": float(settings_row.commission_rate_percent or 0),
                "minimum_payout_amount": float(settings_row.minimum_payout_amount or 0),
                "payout_schedule": settings_row.payout_schedule,
            },
            "inspection": {
                "minimum_inspection_notice_hours": int(settings_row.minimum_inspection_notice_hours),
                "inspection_cancellation_cutoff_hours": int(settings_row.inspection_cancellation_cutoff_hours),
                "missed_inspection_expiry_hours": int(settings_row.missed_inspection_expiry_hours),
            },
            "security": {
                "require_email_verification": bool(settings_row.require_email_verification),
                "require_seller_kyc": bool(settings_row.require_seller_kyc),
                "access_token_lifetime_minutes": int(settings_row.access_token_lifetime_minutes),
                "max_login_attempts": int(settings_row.max_login_attempts),
                "lockout_duration_minutes": int(settings_row.lockout_duration_minutes),
            },
            "notifications": {
                "new_user_notifications": bool(settings_row.new_user_notifications),
                "new_seller_notifications": bool(settings_row.new_seller_notifications),
                "dispute_notifications": bool(settings_row.dispute_notifications),
                "system_alerts": bool(settings_row.system_alerts),
                "weekly_reports": bool(settings_row.weekly_reports),
            },
            "meta": {
                "scope": settings_row.scope,
                "updated_at": settings_row.updated_at,
                "updated_by_user_id": settings_row.updated_by_user_id,
            },
        })

    def update_general(self, db: Session, payload: Dict[str, Any], updated_by_user_id: str) -> SystemSettingsResponse:
        settings_row = self.get_or_create_settings(db)
        for field in (
            "site_name",
            "site_description",
            "contact_email",
            "support_email",
            "currency",
            "language",
            "timezone",
        ):
            if field in payload:
                setattr(settings_row, field, payload[field])
        settings_row.updated_by_user_id = updated_by_user_id
        db.commit()
        db.refresh(settings_row)
        return self.to_response(settings_row)

    def update_payments(self, db: Session, payload: Dict[str, Any], updated_by_user_id: str) -> SystemSettingsResponse:
        settings_row = self.get_or_create_settings(db)
        for field in (
            "commission_rate_percent",
            "minimum_payout_amount",
            "payout_schedule",
        ):
            if field in payload:
                value = payload[field]
                if field.endswith("_percent") or field == "minimum_payout_amount":
                    value = Decimal(str(value))
                setattr(settings_row, field, value)
        settings_row.updated_by_user_id = updated_by_user_id
        db.commit()
        db.refresh(settings_row)
        return self.to_response(settings_row)

    def update_inspection(self, db: Session, payload: Dict[str, Any], updated_by_user_id: str) -> SystemSettingsResponse:
        settings_row = self.get_or_create_settings(db)
        for field in (
            "minimum_inspection_notice_hours",
            "inspection_cancellation_cutoff_hours",
            "missed_inspection_expiry_hours",
        ):
            if field in payload:
                setattr(settings_row, field, payload[field])
        settings_row.updated_by_user_id = updated_by_user_id
        db.commit()
        db.refresh(settings_row)
        return self.to_response(settings_row)

    def update_security(self, db: Session, payload: Dict[str, Any], updated_by_user_id: str) -> SystemSettingsResponse:
        settings_row = self.get_or_create_settings(db)
        for field in (
            "require_email_verification",
            "require_seller_kyc",
            "access_token_lifetime_minutes",
            "max_login_attempts",
            "lockout_duration_minutes",
        ):
            if field in payload:
                setattr(settings_row, field, payload[field])
        settings_row.updated_by_user_id = updated_by_user_id
        db.commit()
        db.refresh(settings_row)
        return self.to_response(settings_row)

    def update_notifications(self, db: Session, payload: Dict[str, Any], updated_by_user_id: str) -> SystemSettingsResponse:
        settings_row = self.get_or_create_settings(db)
        for field in (
            "new_user_notifications",
            "new_seller_notifications",
            "dispute_notifications",
            "system_alerts",
            "weekly_reports",
        ):
            if field in payload:
                setattr(settings_row, field, payload[field])
        settings_row.updated_by_user_id = updated_by_user_id
        db.commit()
        db.refresh(settings_row)
        return self.to_response(settings_row)

    def get_payment_setting_values(self, db: Session) -> Dict[str, Any]:
        settings_row = self.get_or_create_settings(db)
        return {
            "commission_rate_percent": float(settings_row.commission_rate_percent or 0),
            "minimum_payout_amount": float(settings_row.minimum_payout_amount or 0),
            "payout_schedule": settings_row.payout_schedule,
        }

    def get_inspection_setting_values(self, db: Session) -> Dict[str, int]:
        settings_row = self.get_or_create_settings(db)
        return {
            "minimum_inspection_notice_hours": int(settings_row.minimum_inspection_notice_hours),
            "inspection_cancellation_cutoff_hours": int(settings_row.inspection_cancellation_cutoff_hours),
            "missed_inspection_expiry_hours": int(settings_row.missed_inspection_expiry_hours),
        }

    def get_minimum_inspection_notice_hours(self, db: Session) -> int:
        return self.get_inspection_setting_values(db)["minimum_inspection_notice_hours"]

    def get_inspection_cancellation_cutoff_hours(self, db: Session) -> int:
        return self.get_inspection_setting_values(db)["inspection_cancellation_cutoff_hours"]

    def get_missed_inspection_expiry_hours(self, db: Session) -> int:
        return self.get_inspection_setting_values(db)["missed_inspection_expiry_hours"]

    def get_access_token_lifetime_minutes(self, db: Session) -> int:
        return int(self.get_or_create_settings(db).access_token_lifetime_minutes)

    def get_max_login_attempts(self, db: Session) -> int:
        return int(self.get_or_create_settings(db).max_login_attempts)

    def get_lockout_duration_minutes(self, db: Session) -> int:
        return int(self.get_or_create_settings(db).lockout_duration_minutes)

    def is_email_verification_required(self, db: Session) -> bool:
        return bool(self.get_or_create_settings(db).require_email_verification)

    def is_seller_kyc_required(self, db: Session) -> bool:
        return bool(self.get_or_create_settings(db).require_seller_kyc)

    def require_verified_email_for_user(self, db: Session, user_id: str, action: str) -> None:
        if not self.is_email_verification_required(db):
            return

        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        if user.role == "admin" or user.email_verified:
            return

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Email verification is required to {action}",
        )

    def require_approved_seller_kyc(self, db: Session, seller_id: str, action: str) -> None:
        if not self.is_seller_kyc_required(db):
            return

        seller_profile = db.query(SellerProfile).filter(SellerProfile.id == seller_id).first()
        if not seller_profile:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Seller profile not found")
        if seller_profile.kyc_status == "approved":
            return

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Approved seller KYC is required to {action}",
        )

    def should_notify_admins(self, db: Session, event_key: str) -> bool:
        settings_row = self.get_or_create_settings(db)
        mapping = {
            "new_user": settings_row.new_user_notifications,
            "new_seller": settings_row.new_seller_notifications,
            "dispute": settings_row.dispute_notifications,
            "system_alert": settings_row.system_alerts,
            "weekly_report": settings_row.weekly_reports,
        }
        return bool(mapping.get(event_key, False))

    def notify_admins(
        self,
        db: Session,
        event_key: str,
        title: str,
        message: str,
        data: Optional[Dict[str, Any]] = None,
        priority: str = "medium",
        channels: Optional[list[str]] = None,
    ) -> None:
        if not self.should_notify_admins(db, event_key):
            return

        admin_users = db.query(User).filter(User.role == "admin").all()
        for admin in admin_users:
            create_notification(db, {
                "user_id": str(admin.id),
                "type": "system_announcement",
                "title": title,
                "message": message,
                "priority": priority,
                "channels": channels or ["in_app", "email"],
                "data": data or {},
            })


system_settings_service = SystemSettingsService()
