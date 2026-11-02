"""Admin referral campaign management endpoints."""

import math
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import desc, func, or_
from sqlalchemy.orm import Session, joinedload

from core.auth import role_required
from core.model import (
    AuditLog,
    Order,
    Product,
    Profile,
    Referral,
    ReferralCampaign,
    ReferralCampaignProduct,
    ReferralEvent,
    ReferralParticipation,
    ReferralRewardClaim,
    User,
)
from core.referral_service import (
    campaign_effective_status,
    referral_service,
    utcnow,
)
from db.session import get_db
from schemas.referral import ReferralCampaignCreate, ReferralCampaignUpdate

router = APIRouter()


def ok(data, message: str = "OK"):
    return {"success": True, "message": message, "data": data}


def _naive(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    return value.replace(tzinfo=None) if value.tzinfo else value


def _audit(db: Session, admin_id, action: str, target_id=None, details: str = ""):
    try:
        db.add(
            AuditLog(
                admin_id=admin_id,
                target_id=target_id,
                action=action,
                details=details[:4000] if details else None,
            )
        )
    except Exception:
        pass


def _products_for_campaign(db: Session, campaign_id) -> List[ReferralCampaignProduct]:
    return referral_service.campaign_reward_products(db, campaign_id)


def _ser_campaign(db: Session, campaign: ReferralCampaign) -> Dict[str, Any]:
    data = referral_service.serialize_campaign(campaign, db)
    data["stats"] = referral_service.campaign_stats(db, campaign.id)
    data["created_at"] = (
        campaign.created_at.isoformat() if campaign.created_at else None
    )
    data["updated_at"] = (
        campaign.updated_at.isoformat() if campaign.updated_at else None
    )
    return data


def _validate_products(db: Session, product_ids: List[UUID]):
    unique_ids = list(dict.fromkeys(product_ids))
    if not unique_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Select at least one reward product",
        )
    products = (
        db.query(Product)
        .options(joinedload(Product.images))
        .filter(Product.id.in_(unique_ids))
        .all()
    )
    by_id = {product.id: product for product in products}
    missing = [str(pid) for pid in unique_ids if pid not in by_id]
    if missing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown reward product(s): {', '.join(missing)}",
        )
    unavailable = [
        product.name for product in products if product.status != "active"
    ]
    if unavailable:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Only active products can be rewards: {', '.join(unavailable)}",
        )
    ordered = [by_id[pid] for pid in unique_ids]
    return ordered


def _replace_products(db: Session, campaign: ReferralCampaign, products: List[Product]):
    db.query(ReferralCampaignProduct).filter(
        ReferralCampaignProduct.campaign_id == campaign.id
    ).delete(synchronize_session=False)
    for index, product in enumerate(products):
        db.add(
            ReferralCampaignProduct(
                campaign_id=campaign.id,
                product_id=product.id,
                display_order=index,
            )
        )


def _get_campaign(db: Session, campaign_id) -> ReferralCampaign:
    campaign = (
        db.query(ReferralCampaign)
        .filter(ReferralCampaign.id == campaign_id)
        .first()
    )
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    return campaign


@router.get("/campaigns")
def list_campaigns(
    admin=Depends(role_required(["admin"])),
    db: Session = Depends(get_db),
    status_filter: Optional[str] = Query(None, alias="status"),
    search: Optional[str] = None,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
):
    query = db.query(ReferralCampaign)
    if search:
        pattern = f"%{search.strip()}%"
        query = query.filter(
            or_(
                ReferralCampaign.name.ilike(pattern),
                ReferralCampaign.description.ilike(pattern),
            )
        )
    campaigns = query.order_by(desc(ReferralCampaign.created_at)).all()
    rows = [_ser_campaign(db, campaign) for campaign in campaigns]
    if status_filter:
        rows = [row for row in rows if row["status"] == status_filter]

    total = len(rows)
    start = (page - 1) * limit
    return ok(
        {
            "items": rows[start:start + limit],
            "pagination": {
                "page": page,
                "limit": limit,
                "total": total,
                "pages": max(1, math.ceil(total / limit)),
            },
        },
        "Campaigns retrieved",
    )


@router.post("/campaigns", status_code=status.HTTP_201_CREATED)
def create_campaign(
    payload: ReferralCampaignCreate,
    admin=Depends(role_required(["admin"])),
    db: Session = Depends(get_db),
):
    start_at = _naive(payload.start_at)
    end_at = _naive(payload.end_at)
    if start_at >= end_at:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="End date must be after the start date",
        )
    products = _validate_products(db, payload.product_ids)

    campaign = ReferralCampaign(
        name=payload.name.strip(),
        description=payload.description,
        required_referrals=payload.required_referrals,
        start_at=start_at,
        end_at=end_at,
        is_active=False,
        customer_pays_delivery=payload.customer_pays_delivery,
        max_credited_referrals_per_device=payload.max_credited_referrals_per_device,
        created_by=admin["id"],
    )
    db.add(campaign)
    db.flush()
    _replace_products(db, campaign, products)
    _audit(
        db,
        admin["id"],
        "referral_campaign_created",
        campaign.id,
        f"Created campaign {campaign.name}",
    )
    referral_service.log_event(
        db,
        "campaign_created",
        campaign_id=campaign.id,
        actor_user_id=admin["id"],
        details={"name": campaign.name},
    )
    db.commit()
    db.refresh(campaign)
    return ok(_ser_campaign(db, campaign), "Campaign created")


@router.get("/campaigns/{campaign_id}")
def get_campaign(
    campaign_id: UUID,
    admin=Depends(role_required(["admin"])),
    db: Session = Depends(get_db),
):
    campaign = _get_campaign(db, campaign_id)
    return ok(_ser_campaign(db, campaign), "Campaign retrieved")


@router.put("/campaigns/{campaign_id}")
def update_campaign(
    campaign_id: UUID,
    payload: ReferralCampaignUpdate,
    admin=Depends(role_required(["admin"])),
    db: Session = Depends(get_db),
):
    campaign = _get_campaign(db, campaign_id)
    locked = campaign.terms_locked_at is not None

    if payload.required_referrals is not None:
        if locked and payload.required_referrals != campaign.required_referrals:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Required referrals cannot change after activation",
            )
    if payload.customer_pays_delivery is not None:
        if locked and payload.customer_pays_delivery != campaign.customer_pays_delivery:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="The delivery payment policy cannot change after activation",
            )
    if payload.max_credited_referrals_per_device is not None:
        if (
            locked
            and payload.max_credited_referrals_per_device
            != campaign.max_credited_referrals_per_device
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="The device limit cannot change after activation",
            )
    if payload.start_at is not None:
        if locked and _naive(payload.start_at) != campaign.start_at:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="The campaign start date cannot change after activation",
            )

    if payload.name is not None:
        campaign.name = payload.name.strip()
    if payload.description is not None:
        campaign.description = payload.description
    if payload.required_referrals is not None:
        campaign.required_referrals = payload.required_referrals
    if payload.customer_pays_delivery is not None:
        campaign.customer_pays_delivery = payload.customer_pays_delivery
    if payload.max_credited_referrals_per_device is not None:
        campaign.max_credited_referrals_per_device = (
            payload.max_credited_referrals_per_device
        )
    if payload.start_at is not None:
        campaign.start_at = _naive(payload.start_at)
    if payload.end_at is not None:
        new_end = _naive(payload.end_at)
        if locked and new_end < campaign.end_at:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="After activation the end date can only be extended",
            )
        if new_end <= campaign.start_at:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="End date must be after the start date",
            )
        campaign.end_at = new_end
        # Extending an ended campaign makes it schedulable again.
        if campaign.ended_at and new_end > utcnow():
            campaign.ended_at = None

    if payload.product_ids is not None:
        if locked:
            current = [
                link.product_id
                for link in _products_for_campaign(db, campaign.id)
            ]
            if set(current) != set(payload.product_ids):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Reward products cannot change after activation",
                )
        else:
            products = _validate_products(db, payload.product_ids)
            _replace_products(db, campaign, products)

    _audit(
        db,
        admin["id"],
        "referral_campaign_updated",
        campaign.id,
        f"Updated campaign {campaign.name}",
    )
    referral_service.log_event(
        db,
        "campaign_updated",
        campaign_id=campaign.id,
        actor_user_id=admin["id"],
    )
    db.commit()
    db.refresh(campaign)
    return ok(_ser_campaign(db, campaign), "Campaign updated")


@router.post("/campaigns/{campaign_id}/activate")
def activate_campaign(
    campaign_id: UUID,
    admin=Depends(role_required(["admin"])),
    db: Session = Depends(get_db),
):
    campaign = _get_campaign(db, campaign_id)
    products = _products_for_campaign(db, campaign.id)
    if not products:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Add at least one reward product before activating",
        )
    now = utcnow()
    if campaign.end_at <= now:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Extend the end date before activating this campaign",
        )
    campaign.is_active = True
    campaign.ended_at = None
    if campaign.terms_locked_at is None:
        campaign.terms_locked_at = now
    _audit(
        db,
        admin["id"],
        "referral_campaign_activated",
        campaign.id,
        f"Activated campaign {campaign.name}",
    )
    referral_service.log_event(
        db,
        "campaign_activated",
        campaign_id=campaign.id,
        actor_user_id=admin["id"],
    )
    db.commit()
    db.refresh(campaign)
    return ok(_ser_campaign(db, campaign), "Campaign activated")


@router.post("/campaigns/{campaign_id}/deactivate")
def deactivate_campaign(
    campaign_id: UUID,
    admin=Depends(role_required(["admin"])),
    db: Session = Depends(get_db),
):
    campaign = _get_campaign(db, campaign_id)
    campaign.is_active = False
    _audit(
        db,
        admin["id"],
        "referral_campaign_deactivated",
        campaign.id,
        f"Deactivated campaign {campaign.name}",
    )
    referral_service.log_event(
        db,
        "campaign_deactivated",
        campaign_id=campaign.id,
        actor_user_id=admin["id"],
    )
    db.commit()
    db.refresh(campaign)
    return ok(_ser_campaign(db, campaign), "Campaign deactivated")


@router.post("/campaigns/{campaign_id}/end")
def end_campaign(
    campaign_id: UUID,
    admin=Depends(role_required(["admin"])),
    db: Session = Depends(get_db),
):
    campaign = _get_campaign(db, campaign_id)
    campaign.is_active = False
    campaign.ended_at = utcnow()
    _audit(
        db,
        admin["id"],
        "referral_campaign_ended",
        campaign.id,
        f"Ended campaign {campaign.name}",
    )
    referral_service.log_event(
        db,
        "campaign_ended",
        campaign_id=campaign.id,
        actor_user_id=admin["id"],
    )
    db.commit()
    db.refresh(campaign)
    return ok(_ser_campaign(db, campaign), "Campaign ended")


@router.get("/campaigns/{campaign_id}/participants")
def list_participants(
    campaign_id: UUID,
    admin=Depends(role_required(["admin"])),
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    participation_status: Optional[str] = Query(None, alias="status"),
):
    campaign = _get_campaign(db, campaign_id)
    query = (
        db.query(ReferralParticipation)
        .options(
            joinedload(ReferralParticipation.user).joinedload(User.profile),
            joinedload(ReferralParticipation.claim),
            joinedload(ReferralParticipation.referrals).joinedload(Referral.referred),
        )
        .filter(ReferralParticipation.campaign_id == campaign.id)
    )
    if participation_status:
        query = query.filter(
            ReferralParticipation.status == participation_status
        )
    total = query.count()
    rows = (
        query.order_by(desc(ReferralParticipation.created_at))
        .offset((page - 1) * limit)
        .limit(limit)
        .all()
    )
    items = []
    for participation in rows:
        confirmed = sum(
            1 for referral in participation.referrals if referral.status == "confirmed"
        )
        claim = participation.claim
        order = (
            db.query(Order)
            .filter(Order.referral_claim_id == claim.id)
            .first()
            if claim
            else None
        )
        user = participation.user
        profile = getattr(user, "profile", None) if user else None
        items.append(
            {
                "id": str(participation.id),
                "user_id": str(participation.user_id),
                "name": (profile.name if profile else None) or (user.email if user else None),
                "email": user.email if user else None,
                "referral_code": participation.referral_code,
                "status": participation.status,
                "confirmed_referrals": confirmed,
                "required_referrals": campaign.required_referrals,
                "joined_at": (
                    participation.created_at.isoformat()
                    if participation.created_at
                    else None
                ),
                "qualified_at": (
                    participation.qualified_at.isoformat()
                    if participation.qualified_at
                    else None
                ),
                "claim_status": claim.status if claim else None,
                "reward_order_id": str(order.id) if order else None,
                "reward_order_status": order.status if order else None,
                "referrals": [
                    {
                        "id": str(referral.id),
                        "email": (
                            referral.referred.email if referral.referred else None
                        ),
                        "status": referral.status,
                        "rejection_reason": referral.rejection_reason,
                        "device_flagged": bool(
                            referral.status == "rejected"
                            and referral.rejection_reason == "device_limit"
                        ),
                        "registered_at": (
                            referral.registered_at.isoformat()
                            if referral.registered_at
                            else None
                        ),
                        "confirmed_at": (
                            referral.confirmed_at.isoformat()
                            if referral.confirmed_at
                            else None
                        ),
                    }
                    for referral in participation.referrals
                ],
            }
        )
    return ok(
        {
            "items": items,
            "pagination": {
                "page": page,
                "limit": limit,
                "total": total,
                "pages": max(1, math.ceil(total / limit)),
            },
        },
        "Participants retrieved",
    )


@router.get("/campaigns/{campaign_id}/claims")
def list_claims(
    campaign_id: UUID,
    admin=Depends(role_required(["admin"])),
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
):
    campaign = _get_campaign(db, campaign_id)
    query = (
        db.query(ReferralRewardClaim)
        .options(
            joinedload(ReferralRewardClaim.participation).joinedload(
                ReferralParticipation.user
            ),
            joinedload(ReferralRewardClaim.won_product),
        )
        .filter(ReferralRewardClaim.campaign_id == campaign.id)
    )
    total = query.count()
    rows = (
        query.order_by(desc(ReferralRewardClaim.created_at))
        .offset((page - 1) * limit)
        .limit(limit)
        .all()
    )
    items = []
    for claim in rows:
        order = (
            db.query(Order)
            .filter(Order.referral_claim_id == claim.id)
            .first()
        )
        user = claim.participation.user if claim.participation else None
        items.append(
            {
                "id": str(claim.id),
                "participation_id": str(claim.participation_id),
                "customer_email": user.email if user else None,
                "status": claim.status,
                "won_product": (
                    {
                        "id": str(claim.won_product.id),
                        "name": claim.won_product.name,
                        "price": float(claim.won_product.price or 0),
                    }
                    if claim.won_product
                    else None
                ),
                "awarded_at": (
                    claim.awarded_at.isoformat() if claim.awarded_at else None
                ),
                "order": (
                    {
                        "id": str(order.id),
                        "status": order.status,
                        "total_amount": float(order.total_amount or 0),
                        "delivery_fee": float(order.delivery_fee or 0),
                        "payment_status": (
                            "paid"
                            if order.status in ("paid", "shipped", "delivered")
                            else "pending"
                        ),
                    }
                    if order
                    else None
                ),
            }
        )
    return ok(
        {
            "items": items,
            "pagination": {
                "page": page,
                "limit": limit,
                "total": total,
                "pages": max(1, math.ceil(total / limit)),
            },
        },
        "Reward claims retrieved",
    )


@router.get("/campaigns/{campaign_id}/events")
def list_events(
    campaign_id: UUID,
    admin=Depends(role_required(["admin"])),
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
):
    campaign = _get_campaign(db, campaign_id)
    query = db.query(ReferralEvent).filter(
        ReferralEvent.campaign_id == campaign.id
    )
    total = query.count()
    rows = (
        query.order_by(desc(ReferralEvent.created_at))
        .offset((page - 1) * limit)
        .limit(limit)
        .all()
    )
    return ok(
        {
            "items": [
                {
                    "id": str(event.id),
                    "event": event.event,
                    "details": event.details,
                    "actor_user_id": (
                        str(event.actor_user_id) if event.actor_user_id else None
                    ),
                    "created_at": (
                        event.created_at.isoformat() if event.created_at else None
                    ),
                }
                for event in rows
            ],
            "pagination": {
                "page": page,
                "limit": limit,
                "total": total,
                "pages": max(1, math.ceil(total / limit)),
            },
        },
        "Campaign activity retrieved",
    )


@router.post("/{referral_id}/approve")
def approve_referral(
    referral_id: UUID,
    admin=Depends(role_required(["admin"])),
    db: Session = Depends(get_db),
):
    referral = referral_service.approve_rejected_referral(
        db, referral_id, admin["id"]
    )
    _audit(
        db,
        admin["id"],
        "referral_override_approved",
        referral.id,
        "Manually approved a rejected referral",
    )
    db.commit()
    return ok(
        {
            "id": str(referral.id),
            "status": referral.status,
            "confirmed_at": (
                referral.confirmed_at.isoformat() if referral.confirmed_at else None
            ),
        },
        "Referral approved",
    )
