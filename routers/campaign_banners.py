from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from core.auth import role_required
from core.logging_config import get_logger, log_error
from core.model import CampaignBanner
from db.session import engine, get_db
from schemas.campaign_banner import (
    CampaignBannerCreate,
    CampaignBannerOut,
    CampaignBannerUpdate,
    row_to_out,
)

logger = get_logger("routers.campaign_banners")

public_router = APIRouter(tags=["Public Campaigns"])
admin_router = APIRouter(tags=["Admin Campaigns"])

# Resilience: the alembic chain in this repo has multiple heads, so ensure the
# table exists at import time regardless of which migrations have run.
try:
    CampaignBanner.__table__.create(bind=engine, checkfirst=True)
except Exception:
    pass


@public_router.get("/campaign-banners", response_model=dict)
def list_public_campaign_banners(db: Session = Depends(get_db)):
    """Active home-carousel banners, ordered (slide #1 is the bundled local
    campaign image on clients; these follow it)."""
    rows = (
        db.query(CampaignBanner)
        .filter(CampaignBanner.is_active.is_(True))
        .order_by(CampaignBanner.display_order.asc(), CampaignBanner.created_at.asc())
        .all()
    )
    return {"success": True, "data": [row_to_out(r).model_dump() for r in rows]}


@admin_router.get("/campaign-banners", response_model=dict)
def admin_list_campaign_banners(
    include_inactive: bool = True,
    user=Depends(role_required(["admin"])),
    db: Session = Depends(get_db),
):
    """All banners for the admin settings screen."""
    q = db.query(CampaignBanner)
    if not include_inactive:
        q = q.filter(CampaignBanner.is_active.is_(True))
    rows = q.order_by(CampaignBanner.display_order.asc(), CampaignBanner.created_at.asc()).all()
    return {"success": True, "data": [row_to_out(r).model_dump() for r in rows]}


@admin_router.post("/campaign-banners", response_model=dict)
def admin_create_campaign_banner(
    payload: CampaignBannerCreate,
    user=Depends(role_required(["admin"])),
    db: Session = Depends(get_db),
):
    """Upload a new banner (image_url comes from the admin's Cloudinary upload)."""
    try:
        row = CampaignBanner(
            title=payload.title or "",
            subtitle=payload.subtitle,
            image_url=payload.image_url,
            cta_text=payload.cta_text,
            cta_link=payload.cta_link,
            display_order=payload.display_order,
            is_active=payload.is_active,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return {"success": True, "message": "Banner created", "data": row_to_out(row).model_dump()}
    except Exception as e:
        db.rollback()
        log_error(logger, "Failed to create campaign banner", e, user_id=user.get("id"))
        raise HTTPException(status_code=500, detail="Failed to create banner")


@admin_router.put("/campaign-banners/{banner_id}", response_model=dict)
def admin_update_campaign_banner(
    banner_id: UUID,
    payload: CampaignBannerUpdate,
    user=Depends(role_required(["admin"])),
    db: Session = Depends(get_db),
):
    """Edit a banner: copy, image, CTA, order, or active flag (admin settings)."""
    try:
        row = db.query(CampaignBanner).filter(CampaignBanner.id == banner_id).first()
        if not row:
            raise HTTPException(status_code=404, detail="Banner not found")
        for field in ("title", "subtitle", "image_url", "cta_text", "cta_link", "display_order", "is_active"):
            value = getattr(payload, field)
            if value is not None:
                setattr(row, field, value)
        db.commit()
        db.refresh(row)
        return {"success": True, "message": "Banner updated", "data": row_to_out(row).model_dump()}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        log_error(logger, "Failed to update campaign banner", e, user_id=user.get("id"))
        raise HTTPException(status_code=500, detail="Failed to update banner")


@admin_router.delete("/campaign-banners/{banner_id}", response_model=dict)
def admin_delete_campaign_banner(
    banner_id: UUID,
    user=Depends(role_required(["admin"])),
    db: Session = Depends(get_db),
):
    try:
        row = db.query(CampaignBanner).filter(CampaignBanner.id == banner_id).first()
        if not row:
            raise HTTPException(status_code=404, detail="Banner not found")
        db.delete(row)
        db.commit()
        return {"success": True, "message": "Banner deleted"}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        log_error(logger, "Failed to delete campaign banner", e, user_id=user.get("id"))
        raise HTTPException(status_code=500, detail="Failed to delete banner")
