from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from uuid import UUID
from typing import List, Dict, Any

from db.session import get_db, SessionLocal
from core.auth import get_current_user
from core.asset_service import asset_service
from core.notifications_service import create_notification
from schemas.assets import (
    AssetInspectionResponse,
    AssetInspectionSchedule,
    AssetInspectionReview,
    AssetAgreementResponse,
    AssetPaymentResponse,
    AssetInspectionComplete,
    AssetAgreementBase,
    AgreementPaymentInitialize,
    AgreementPaymentVerify,
    AssetAgreementApprove,
)


router = APIRouter(prefix="", tags=["Assets"])

def notify_agreement_update(target_id: str, agreement_type: str, action: str):
    """Background task to create notifications with its own session"""
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

@router.get("/inspections", response_model=List[AssetInspectionResponse])
def list_my_inspections(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """List all inspections for the current user (Customer or Seller)"""
    if current_user["role"] == "seller":
        return asset_service.list_seller_inspections(db, UUID(current_user["id"]))
    else:
        return asset_service.list_user_inspections(db, UUID(current_user["id"]))

@router.get("/inspections/{id}", response_model=AssetInspectionResponse)
def get_inspection_details(
    id: UUID,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Get details for a specific inspection"""
    inspection = asset_service.get_inspection(db, UUID(current_user["id"]), id)
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
    current_user: dict = Depends(get_current_user)
):
    """Review an inspection request (Seller)"""
    if current_user["role"] not in ["seller", "admin"]:
        raise HTTPException(status_code=403, detail="Only sellers can review inspections")
    
    return asset_service.review_inspection(db, UUID(current_user["id"]), id, body)

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
    
    # Notify the other party
    target_id = str(inspection.seller_id) if current_user["role"] != "seller" else str(inspection.user_id)
    background_tasks.add_task(notify_agreement_update, target_id, inspection.asset_type, "created")
    
    return inspection

@router.post("/agreements", response_model=AssetAgreementResponse)
async def create_agreement(
    data: AssetAgreementBase,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    user_id = UUID(current_user["id"])
    is_seller = current_user["role"] == "seller"
    agreement = asset_service.create_agreement(db, user_id, data, is_seller=is_seller)
    
    # Notify the other party in background
    target_id = str(agreement.seller_id) if not is_seller else str(agreement.user_id)
    background_tasks.add_task(notify_agreement_update, target_id, data.asset_type, "created")
    
    return agreement

@router.post("/agreements/{id}/approve", response_model=AssetAgreementResponse)
async def approve_agreement(
    id: UUID,
    body: AssetAgreementApprove,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    if current_user["role"] != "seller":
        raise HTTPException(status_code=403, detail="Only sellers can approve agreements")
    
    seller_id = UUID(current_user["id"])
    agreement = asset_service.approve_agreement(db, seller_id, id, body.unit_id)
    
    # Notify the buyer in background
    background_tasks.add_task(notify_agreement_update, str(agreement.user_id), agreement.asset_type, "approved")
    
    return agreement

@router.post("/agreements/{id}/reject", response_model=AssetAgreementResponse)
async def reject_agreement(
    id: UUID,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    if current_user["role"] != "seller":
        raise HTTPException(status_code=403, detail="Only sellers can reject agreements")
    
    seller_id = UUID(current_user["id"])
    agreement = asset_service.reject_agreement(db, seller_id, id)
    
    # Notify the buyer in background
    background_tasks.add_task(notify_agreement_update, str(agreement.user_id), agreement.asset_type, "rejected")
    
    return agreement

@router.get("/agreements", response_model=List[AssetAgreementResponse])
def list_my_agreements(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """List all agreements for the current user"""
    if current_user["role"] == "seller":
        return asset_service.list_seller_agreements(db, UUID(current_user["id"]))
    else:
        return asset_service.list_user_agreements(db, UUID(current_user["id"]))

@router.get("/payments", response_model=List[AssetPaymentResponse])
def get_asset_payments(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Get list of payments for the current user/seller"""
    if current_user["role"] == "seller":
        return asset_service.list_seller_payments(db, UUID(current_user["id"]))
    else:
        return asset_service.list_user_payments(db, UUID(current_user["id"]))

@router.get("/payments/{id}", response_model=AssetPaymentResponse)
def get_payment_details(
    id: UUID,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Get details for a specific payment"""
    payment = asset_service.get_payment(db, UUID(current_user["id"]), id)
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
    agreement = asset_service.get_agreement(db, UUID(current_user["id"]), id)
    if not agreement:
        raise HTTPException(status_code=404, detail="Agreement not found or unauthorized")
    return agreement


@router.delete("/inspections/{id}")
def delete_inspection(
    id: UUID,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Delete an inspection record (Customer or Seller)"""
    return asset_service.delete_inspection(db, UUID(current_user["id"]), id)

@router.post("/agreements/{id}/cancel", response_model=AssetAgreementResponse)
def cancel_agreement(
    id: UUID,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Cancel an agreement before deposit (Customer only)"""
    if current_user["role"] != "customer":
        raise HTTPException(status_code=403, detail="Only customers can cancel their agreements")
        
    agreement = asset_service.cancel_agreement(db, UUID(current_user["id"]), id)
    
    # Notify the seller in background
    background_tasks.add_task(notify_agreement_update, str(agreement.seller_id), agreement.asset_type, "cancelled")
    
    return agreement
