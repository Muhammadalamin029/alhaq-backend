import json
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from core.auth import role_required
from core.legal_document_html import structure_to_html
from core.logging_config import get_logger, log_error
from core.model import LegalDocument
from db.session import get_db
from schemas.legal_document import (
    LegalDocumentOut,
    LegalDocumentUpdate,
    parse_structure_from_db,
)

logger = get_logger("routers.legal_documents")

ALLOWED_SLUGS = frozenset({"terms", "privacy"})

public_router = APIRouter(tags=["Public Legal"])
admin_router = APIRouter(tags=["Admin Legal"])


def _row_to_out(row: LegalDocument | None, slug: str | None = None) -> LegalDocumentOut:
    if not row:
        return LegalDocumentOut(
            slug=slug or "",
            body_html=None,
            effective_date_label=None,
            effective_date=None,
            structure=None,
            updated_at=None,
        )
    structure = parse_structure_from_db(row.structure_json)
    eff = row.effective_date.isoformat() if row.effective_date else None
    return LegalDocumentOut(
        slug=row.slug,
        body_html=row.body_html,
        effective_date_label=row.effective_date_label,
        effective_date=eff,
        structure=structure,
        updated_at=row.updated_at.isoformat() if row.updated_at else None,
    )


@public_router.get("/legal/{slug}", response_model=dict)
def get_public_legal(slug: str, db: Session = Depends(get_db)):
    if slug not in ALLOWED_SLUGS:
        raise HTTPException(status_code=404, detail="Unknown legal document")
    row = db.query(LegalDocument).filter(LegalDocument.slug == slug).first()
    data = _row_to_out(row, slug=slug).model_dump()
    return {"success": True, "data": data}


@admin_router.put("/legal/{slug}", response_model=dict)
def upsert_legal_document(
    slug: str,
    payload: LegalDocumentUpdate,
    user=Depends(role_required(["admin"])),
    db: Session = Depends(get_db),
):
    if slug not in ALLOWED_SLUGS:
        raise HTTPException(status_code=400, detail="Invalid slug")

    try:
        row = db.query(LegalDocument).filter(LegalDocument.slug == slug).first()
        if not row:
            row = LegalDocument(slug=slug)
            db.add(row)

        row.structure_json = json.dumps(payload.structure.model_dump(), ensure_ascii=False)
        row.body_html = structure_to_html(payload.structure)
        row.effective_date = payload.effective_date
        if payload.effective_date:
            row.effective_date_label = payload.effective_date.strftime("%B %d, %Y")
        else:
            row.effective_date_label = None

        db.commit()
        db.refresh(row)
        return {
            "success": True,
            "message": "Legal document saved",
            "data": _row_to_out(row).model_dump(),
        }
    except Exception as e:
        db.rollback()
        log_error(logger, "Failed to save legal document", e, user_id=user.get("id"))
        raise HTTPException(status_code=500, detail="Failed to save legal document")
