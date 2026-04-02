from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from core.auth import role_required
from core.logging_config import get_logger, log_error
from core.system_settings_service import system_settings_service
from db.session import get_db
from schemas.system_settings import (
    SystemSettingsResponse,
    UpdateSystemSettingsGeneralRequest,
    UpdateSystemSettingsInspectionRequest,
    UpdateSystemSettingsNotificationsRequest,
    UpdateSystemSettingsPaymentsRequest,
    UpdateSystemSettingsSecurityRequest,
)


router = APIRouter()
system_settings_logger = get_logger("routers.system_settings")


@router.get("", response_model=dict)
def get_system_settings(
    user=Depends(role_required(["admin"])),
    db: Session = Depends(get_db),
):
    try:
        settings_data = system_settings_service.get_settings(db)
        return {
            "success": True,
            "message": "System settings retrieved successfully",
            "data": settings_data.model_dump(),
        }
    except HTTPException:
        raise
    except Exception as e:
        log_error(system_settings_logger, "Failed to fetch system settings", e, user_id=user["id"])
        raise HTTPException(status_code=500, detail="Failed to fetch system settings")


@router.put("/general", response_model=dict)
def update_general_settings(
    payload: UpdateSystemSettingsGeneralRequest,
    user=Depends(role_required(["admin"])),
    db: Session = Depends(get_db),
):
    try:
        settings_data = system_settings_service.update_general(
            db,
            payload.model_dump(),
            user["id"],
        )
        return {
            "success": True,
            "message": "General settings updated successfully",
            "data": settings_data.model_dump(),
        }
    except HTTPException:
        raise
    except Exception as e:
        log_error(system_settings_logger, "Failed to update general settings", e, user_id=user["id"])
        raise HTTPException(status_code=500, detail="Failed to update general settings")


@router.put("/payments", response_model=dict)
def update_payment_settings(
    payload: UpdateSystemSettingsPaymentsRequest,
    user=Depends(role_required(["admin"])),
    db: Session = Depends(get_db),
):
    try:
        settings_data = system_settings_service.update_payments(
            db,
            payload.model_dump(),
            user["id"],
        )
        return {
            "success": True,
            "message": "Payment settings updated successfully",
            "data": settings_data.model_dump(),
        }
    except HTTPException:
        raise
    except Exception as e:
        log_error(system_settings_logger, "Failed to update payment settings", e, user_id=user["id"])
        raise HTTPException(status_code=500, detail="Failed to update payment settings")


@router.put("/inspection", response_model=dict)
def update_inspection_settings(
    payload: UpdateSystemSettingsInspectionRequest,
    user=Depends(role_required(["admin"])),
    db: Session = Depends(get_db),
):
    try:
        settings_data = system_settings_service.update_inspection(
            db,
            payload.model_dump(),
            user["id"],
        )
        return {
            "success": True,
            "message": "Inspection settings updated successfully",
            "data": settings_data.model_dump(),
        }
    except HTTPException:
        raise
    except Exception as e:
        log_error(system_settings_logger, "Failed to update inspection settings", e, user_id=user["id"])
        raise HTTPException(status_code=500, detail="Failed to update inspection settings")


@router.put("/security", response_model=dict)
def update_security_settings(
    payload: UpdateSystemSettingsSecurityRequest,
    user=Depends(role_required(["admin"])),
    db: Session = Depends(get_db),
):
    try:
        settings_data = system_settings_service.update_security(
            db,
            payload.model_dump(),
            user["id"],
        )
        return {
            "success": True,
            "message": "Security settings updated successfully",
            "data": settings_data.model_dump(),
        }
    except HTTPException:
        raise
    except Exception as e:
        log_error(system_settings_logger, "Failed to update security settings", e, user_id=user["id"])
        raise HTTPException(status_code=500, detail="Failed to update security settings")


@router.put("/notifications", response_model=dict)
def update_notification_settings(
    payload: UpdateSystemSettingsNotificationsRequest,
    user=Depends(role_required(["admin"])),
    db: Session = Depends(get_db),
):
    try:
        settings_data = system_settings_service.update_notifications(
            db,
            payload.model_dump(),
            user["id"],
        )
        return {
            "success": True,
            "message": "Notification settings updated successfully",
            "data": settings_data.model_dump(),
        }
    except HTTPException:
        raise
    except Exception as e:
        log_error(system_settings_logger, "Failed to update notification settings", e, user_id=user["id"])
        raise HTTPException(status_code=500, detail="Failed to update notification settings")
