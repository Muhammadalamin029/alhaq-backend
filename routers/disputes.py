from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from uuid import UUID

from core.auth import role_required
from db.session import get_db
from core.dispute_service import dispute_service
from schemas.dispute import DisputeCreate, DisputeUpdate, DisputeResponse, DisputeListResponse, DisputeSingleResponse
from core.system_settings_service import system_settings_service

router = APIRouter()

@router.post("/", response_model=DisputeSingleResponse)
async def create_dispute(
    request: DisputeCreate,
    user=Depends(role_required(["customer"])),
    db: Session = Depends(get_db)
):
    try:
        system_settings_service.require_verified_email_for_user(db, user["id"], "create a dispute")
        dispute = dispute_service.create_dispute(db, user["id"], request)
        return DisputeSingleResponse(
            success=True,
            message="Dispute created successfully",
            data=dispute
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/", response_model=DisputeListResponse)
async def get_disputes(
    user=Depends(role_required(["customer", "admin"])),
    db: Session = Depends(get_db)
):
    try:
        user_id = user["id"] if user["role"] == "customer" else None
        disputes = dispute_service.get_disputes(db, user_id)
        return DisputeListResponse(
            success=True,
            message="Disputes retrieved",
            data=disputes
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.patch("/{id}", response_model=DisputeSingleResponse)
async def update_dispute(
    id: UUID,
    request: DisputeUpdate,
    user=Depends(role_required(["admin"])),
    db: Session = Depends(get_db)
):
    try:
        dispute = dispute_service.update_dispute(db, str(id), user["id"], request)
        return DisputeSingleResponse(
            success=True,
            message="Dispute updated successfully",
            data=dispute
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
