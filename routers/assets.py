from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from uuid import UUID
from typing import List

from db.session import get_db, SessionLocal
from core.auth import get_current_user, role_required
from core.asset_service import asset_service
from core.notifications_service import create_notification
from core.system_settings_service import system_settings_service
from core.store_service import get_store_id
from schemas.assets import (
    AssetInspectionResponse,
    AssetInspectionSchedule,
    AssetInspectionReview,
    AssetAgreementResponse,
    AssetPaymentResponse,
    AssetInspectionComplete,
    AssetAgreementBase,
    AssetAgreementApprove,
)


router = APIRouter(prefix="", tags=["Assets"])

def notify_agreement_update(target_id: str, agreement_type: str, action: str):
    """Background task to notify a buyer with its own session"""
    db = SessionLocal()
    try:
        title = "New Purchase Agreement" if action == "created" else "Agreement Approved"
        message = (
            f"A new agreement has been submitted for review. Please check your agreements list."
            if action == "created" else
            f"Your purchase agreement has been approved! You can now proceed with the deposit."
        )

        create_notification(db, {
            "user_id": target_id,
            "type": "agreement_update",
            "title": title,
            "message": message,
            "priority": "high"
        })
    finally:
        db.close()


def notify_admins_of_agreement_event(agreement_type: str, action: str):
    """Background task to notify admins (there's no more per-listing seller user to notify)"""
    db = SessionLocal()
    try:
        messages = {
            "created": ("New Purchase Agreement", f"A new {agreement_type} agreement has been submitted and is pending review."),
            "cancelled": ("Agreement Cancelled By Buyer", f"A buyer has cancelled their {agreement_type} agreement."),
        }
        title, message = messages.get(action, ("Agreement Update", f"An agreement update occurred for a {agreement_type} listing: {action}."))
        system_settings_service.notify_admins(
            db=db,
            event_key="system_alert",
            title=title,
            message=message,
            priority="medium",
        )
    finally:
        db.close()


@router.get("/inspections", response_model=List[AssetInspectionResponse])
def list_my_inspections(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """List all inspections for the current user (Customer or Admin)"""
    if current_user["role"] == "admin":
        return asset_service.list_seller_inspections(db, get_store_id(db))
    else:
        return asset_service.list_user_inspections(db, UUID(current_user["id"]))

@router.get("/inspections/{id}", response_model=AssetInspectionResponse)
def get_inspection_details(
    id: UUID,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Get details for a specific inspection"""
    lookup_id = get_store_id(db) if current_user["role"] == "admin" else UUID(current_user["id"])
    inspection = asset_service.get_inspection(db, lookup_id, id)
    if not inspection:
        raise HTTPException(status_code=404, detail="Inspection not found or unauthorized")
    return inspection

@router.post("/inspections/schedule", response_model=AssetInspectionResponse)
def schedule_asset_inspection(
    data: AssetInspectionSchedule,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Schedule a new asset inspection (Customer)"""
    return asset_service.schedule_inspection(db, UUID(current_user["id"]), data)

@router.post("/inspections/{id}/review", response_model=AssetInspectionResponse)
def review_asset_inspection(
    id: UUID,
    body: AssetInspectionReview,
    db: Session = Depends(get_db),
    current_user: dict = Depends(role_required(["admin"]))
):
    """Review an inspection request (Admin)"""
    return asset_service.review_inspection(db, get_store_id(db), id, body)

@router.post("/inspections/{inspection_id}/complete", response_model=AssetInspectionResponse)
async def complete_inspection(
    inspection_id: UUID,
    data: AssetInspectionComplete,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    user_id = UUID(current_user["id"])
    inspection = asset_service.complete_inspection(db, user_id, inspection_id, data)

    # Notify admins that an agreement is now pending review
    background_tasks.add_task(notify_admins_of_agreement_event, inspection.asset_type, "created")

    return inspection

@router.post("/agreements", response_model=AssetAgreementResponse)
async def create_agreement(
    data: AssetAgreementBase,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    user_id = UUID(current_user["id"])
    agreement = asset_service.create_agreement(db, user_id, data, is_seller=False)

    # Notify admins in background
    background_tasks.add_task(notify_admins_of_agreement_event, data.asset_type, "created")

    return agreement

@router.post("/agreements/{id}/approve", response_model=AssetAgreementResponse)
async def approve_agreement(
    id: UUID,
    body: AssetAgreementApprove,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: dict = Depends(role_required(["admin"]))
):
    """Approve a pending agreement (Admin)"""
    agreement = asset_service.approve_agreement(db, get_store_id(db), id, body.unit_id)

    # Notify the buyer in background
    background_tasks.add_task(notify_agreement_update, str(agreement.user_id), agreement.asset_type, "approved")

    return agreement

@router.post("/agreements/{id}/reject", response_model=AssetAgreementResponse)
async def reject_agreement(
    id: UUID,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: dict = Depends(role_required(["admin"]))
):
    """Reject a pending agreement (Admin)"""
    agreement = asset_service.reject_agreement(db, get_store_id(db), id)

    # Notify the buyer in background
    background_tasks.add_task(notify_agreement_update, str(agreement.user_id), agreement.asset_type, "rejected")

    return agreement

@router.get("/agreements", response_model=List[AssetAgreementResponse])
def list_my_agreements(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """List all agreements for the current user"""
    if current_user["role"] == "admin":
        return asset_service.list_seller_agreements(db, get_store_id(db))
    else:
        return asset_service.list_user_agreements(db, UUID(current_user["id"]))

@router.get("/payments", response_model=List[AssetPaymentResponse])
def get_asset_payments(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Get list of payments for the current user (or all store payments for admin)"""
    if current_user["role"] == "admin":
        return asset_service.list_seller_payments(db, get_store_id(db))
    else:
        return asset_service.list_user_payments(db, UUID(current_user["id"]))

@router.get("/payments/{id}", response_model=AssetPaymentResponse)
def get_payment_details(
    id: UUID,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Get details for a specific payment"""
    lookup_id = get_store_id(db) if current_user["role"] == "admin" else UUID(current_user["id"])
    payment = asset_service.get_payment(db, lookup_id, id)
    if not payment:
        raise HTTPException(status_code=404, detail="Payment not found or unauthorized")
    return payment

@router.get("/agreements/{id}", response_model=AssetAgreementResponse)
def get_agreement_details(
    id: UUID,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Get details for a specific agreement"""
    lookup_id = get_store_id(db) if current_user["role"] == "admin" else UUID(current_user["id"])
    agreement = asset_service.get_agreement(db, lookup_id, id)
    if not agreement:
        raise HTTPException(status_code=404, detail="Agreement not found or unauthorized")
    return agreement


@router.delete("/inspections/{id}")
def delete_inspection(
    id: UUID,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Delete an inspection record (Customer or Admin)"""
    lookup_id = get_store_id(db) if current_user["role"] == "admin" else UUID(current_user["id"])
    return asset_service.delete_inspection(db, lookup_id, id)

@router.post("/agreements/{id}/cancel", response_model=AssetAgreementResponse)
def cancel_agreement(
    id: UUID,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: dict = Depends(role_required(["customer"]))
):
    """Cancel an agreement before deposit (Customer only)"""
    agreement = asset_service.cancel_agreement(db, UUID(current_user["id"]), id)

    # Notify admins in background
    background_tasks.add_task(notify_admins_of_agreement_event, agreement.asset_type, "cancelled")

    return agreement
