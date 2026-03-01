from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from uuid import UUID
from typing import List, Dict, Any

from db.session import get_db
from core.auth import get_current_user
from core.asset_service import asset_service
from schemas.assets import (
    AssetInspectionResponse,
    AssetInspectionSchedule,
    AssetInspectionReview,
    AssetAgreementResponse,
    AssetPaymentResponse,
    AssetInspectionComplete,
    AssetAgreementBase,
)


router = APIRouter(prefix="", tags=["Assets"])

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
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    user_id = UUID(current_user["id"])
    return asset_service.complete_inspection(db, user_id, inspection_id, data)

@router.post("/agreements", response_model=AssetAgreementResponse)
async def create_agreement(
    data: AssetAgreementBase,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    if current_user["role"] != "seller":
        raise HTTPException(status_code=403, detail="Only sellers can create agreements")
    seller_id = UUID(current_user["id"])
    return asset_service.create_agreement(db, seller_id, data)

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
