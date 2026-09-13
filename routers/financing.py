from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Query
from sqlalchemy.orm import Session
from uuid import UUID
from typing import List, Optional

from db.session import get_db
from core.auth import get_current_user, role_required
from core.financing_service import financing_service
from schemas.financing import (
    FinancingDocumentRequirementOut,
    FinancingDocumentRequirementCreate,
    FinancingDocumentRequirementUpdate,
    FinancingDocumentRequirementStatus,
    FinancingApplicationOut,
    FinancingApplicationSubmit,
    FinancingApplicationDecision,
)
from schemas.admin import AdminListResponse

router = APIRouter(tags=["Financing"])
admin_router = APIRouter(tags=["Admin Financing"])


# ---------------- Customer ----------------

@router.get("/document-requirements", response_model=List[FinancingDocumentRequirementOut])
def get_active_document_requirements(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    return financing_service.list_active_document_requirements(db)


@router.get("/applications/me", response_model=Optional[FinancingApplicationOut])
def get_my_application(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    user_id = UUID(current_user["id"])
    return financing_service.get_my_application(db, user_id)


@router.post("/applications", response_model=FinancingApplicationOut)
def submit_application(
    data: FinancingApplicationSubmit,
    db: Session = Depends(get_db),
    current_user: dict = Depends(role_required(["customer"])),
):
    user_id = UUID(current_user["id"])
    return financing_service.submit_application(db, user_id, data)


# ---------------- Admin ----------------

@admin_router.get("/document-requirements", response_model=List[FinancingDocumentRequirementOut])
def admin_list_document_requirements(
    db: Session = Depends(get_db),
    current_user: dict = Depends(role_required(["admin"])),
):
    return financing_service.list_all_document_requirements(db)


@admin_router.post("/document-requirements", response_model=FinancingDocumentRequirementOut)
def admin_create_document_requirement(
    data: FinancingDocumentRequirementCreate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(role_required(["admin"])),
):
    return financing_service.create_document_requirement(db, data)


@admin_router.put("/document-requirements/{requirement_id}", response_model=FinancingDocumentRequirementOut)
def admin_update_document_requirement(
    requirement_id: UUID,
    data: FinancingDocumentRequirementUpdate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(role_required(["admin"])),
):
    return financing_service.update_document_requirement(db, requirement_id, data)


@admin_router.patch("/document-requirements/{requirement_id}/status", response_model=FinancingDocumentRequirementOut)
def admin_set_document_requirement_status(
    requirement_id: UUID,
    data: FinancingDocumentRequirementStatus,
    db: Session = Depends(get_db),
    current_user: dict = Depends(role_required(["admin"])),
):
    return financing_service.set_document_requirement_active(db, requirement_id, data.is_active)


@admin_router.get("/applications", response_model=AdminListResponse)
def admin_list_applications(
    status: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: dict = Depends(role_required(["admin"])),
):
    applications, total = financing_service.list_applications(db, status=status, page=page, limit=limit)
    data = [FinancingApplicationOut.model_validate(a).model_dump(mode="json") for a in applications]
    return {
        "success": True,
        "message": "Financing applications retrieved",
        "data": data,
        "pagination": {"page": page, "limit": limit, "total": total},
        "total": total,
    }


@admin_router.get("/applications/{application_id}", response_model=FinancingApplicationOut)
def admin_get_application(
    application_id: UUID,
    db: Session = Depends(get_db),
    current_user: dict = Depends(role_required(["admin"])),
):
    return financing_service.get_application(db, application_id)


@admin_router.post("/applications/{application_id}/approve", response_model=FinancingApplicationOut)
def admin_approve_application(
    application_id: UUID,
    db: Session = Depends(get_db),
    current_user: dict = Depends(role_required(["admin"])),
):
    admin_id = UUID(current_user["id"])
    return financing_service.approve_application(db, admin_id, application_id)


@admin_router.post("/applications/{application_id}/reject", response_model=FinancingApplicationOut)
def admin_reject_application(
    application_id: UUID,
    body: FinancingApplicationDecision,
    db: Session = Depends(get_db),
    current_user: dict = Depends(role_required(["admin"])),
):
    admin_id = UUID(current_user["id"])
    return financing_service.reject_application(db, admin_id, application_id, body.reason)


@admin_router.post("/applications/{application_id}/revoke", response_model=FinancingApplicationOut)
def admin_revoke_application(
    application_id: UUID,
    body: FinancingApplicationDecision,
    db: Session = Depends(get_db),
    current_user: dict = Depends(role_required(["admin"])),
):
    admin_id = UUID(current_user["id"])
    return financing_service.revoke_application(db, admin_id, application_id, body.reason)
