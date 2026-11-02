"""Customer-facing referral campaign endpoints."""

from decimal import Decimal
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session, joinedload

from core.auth import role_required
from core.delivery_service import resolve_delivery_fee
from core.model import Address, ReferralCampaign, ReferralParticipation
from core.referral_service import (
    campaign_effective_status,
    referral_service,
)
from core.system_settings_service import system_settings_service
from db.session import get_db
from schemas.referral import ReferralOrderCreate

router = APIRouter()


def ok(data, message: str = "OK"):
    return {"success": True, "message": message, "data": data}


def _order_summary(order) -> dict:
    return {
        "id": str(order.id),
        "status": order.status,
        "order_type": order.order_type,
        "total_amount": float(order.total_amount or 0),
        "delivery_fee": float(order.delivery_fee or 0),
        "delivery_address_id": (
            str(order.delivery_address) if order.delivery_address else None
        ),
        "created_at": order.created_at.isoformat() if order.created_at else None,
        "payment_required": float(order.total_amount or 0) > 0,
    }


@router.get("/campaigns")
def list_campaigns(
    user=Depends(role_required(["customer"])),
    db: Session = Depends(get_db),
):
    """Active campaigns for the customer, with their participation state."""
    referral_service.reconcile_for_user(db, user["id"])
    return ok(
        referral_service.list_available_campaigns(db, user["id"]),
        "Campaigns retrieved",
    )


@router.get("/campaigns/{campaign_id}")
def get_campaign(
    campaign_id: UUID,
    user=Depends(role_required(["customer"])),
    db: Session = Depends(get_db),
):
    campaign = (
        db.query(ReferralCampaign)
        .options(
            joinedload(ReferralCampaign.products),
        )
        .filter(ReferralCampaign.id == campaign_id)
        .first()
    )
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    participation = (
        db.query(ReferralParticipation)
        .options(
            joinedload(ReferralParticipation.campaign),
            joinedload(ReferralParticipation.claim),
        )
        .filter(
            ReferralParticipation.campaign_id == campaign.id,
            ReferralParticipation.user_id == user["id"],
        )
        .first()
    )
    state = campaign_effective_status(campaign)
    if state != "active" and not participation:
        raise HTTPException(status_code=404, detail="Campaign not found")

    if participation:
        referral_service.reconcile_for_user(db, user["id"])
        db.refresh(participation)

    data = referral_service.serialize_campaign(campaign, db)
    data["joined"] = participation is not None
    data["participation"] = (
        referral_service.serialize_participation(db, participation)
        if participation
        else None
    )
    return ok(data, "Campaign retrieved")


@router.get("/validate/{code}")
def validate_code(code: str, db: Session = Depends(get_db)):
    """Public check used by the registration page.

    Deliberately returns only the campaign name and the referrer's first name,
    never an email address or customer identifier.
    """
    normalized = (code or "").strip().upper()
    if not normalized:
        raise HTTPException(status_code=400, detail="Referral code is required")

    participation = (
        db.query(ReferralParticipation)
        .options(
            joinedload(ReferralParticipation.campaign),
            joinedload(ReferralParticipation.user),
        )
        .filter(ReferralParticipation.referral_code == normalized)
        .first()
    )
    if not participation or not participation.campaign:
        raise HTTPException(status_code=404, detail="Invalid referral link")

    campaign = participation.campaign
    if not referral_service_window_open_public(campaign):
        raise HTTPException(status_code=410, detail="This referral link has expired")

    referrer = participation.user
    first_name = None
    if referrer:
        profile_name = getattr(getattr(referrer, "profile", None), "name", None)
        display = profile_name or referrer.email or ""
        first_name = display.split("@")[0].split(" ")[0][:40] or None

    return ok(
        {
            "campaign_id": str(campaign.id),
            "campaign_name": campaign.name,
            "required_referrals": campaign.required_referrals,
            "referrer_name": first_name,
            "ends_at": campaign.end_at.isoformat() if campaign.end_at else None,
        },
        "Referral link is valid",
    )


def referral_service_window_open_public(campaign: ReferralCampaign) -> bool:
    from core.referral_service import campaign_effective_status as effective

    return effective(campaign) == "active"


@router.post("/campaigns/{campaign_id}/join")
def join_campaign(
    campaign_id: UUID,
    user=Depends(role_required(["customer"])),
    db: Session = Depends(get_db),
):
    system_settings_service.require_verified_email_for_user(
        db, user["id"], "join a referral campaign"
    )
    participation = referral_service.join_campaign(db, campaign_id, user["id"])
    participation = (
        db.query(ReferralParticipation)
        .options(
            joinedload(ReferralParticipation.campaign),
            joinedload(ReferralParticipation.claim),
        )
        .filter(ReferralParticipation.id == participation.id)
        .first()
    )
    return ok(
        referral_service.serialize_participation(db, participation),
        "Joined campaign",
    )


@router.get("/me")
def my_referrals(
    user=Depends(role_required(["customer"])),
    db: Session = Depends(get_db),
):
    referral_service.reconcile_for_user(db, user["id"])
    participations = (
        db.query(ReferralParticipation)
        .options(
            joinedload(ReferralParticipation.campaign),
            joinedload(ReferralParticipation.claim),
        )
        .filter(ReferralParticipation.user_id == user["id"])
        .order_by(ReferralParticipation.created_at.desc())
        .all()
    )
    return ok(
        [
            referral_service.serialize_participation(db, participation)
            for participation in participations
        ],
        "Your referral campaigns",
    )


@router.get("/participations/{participation_id}")
def get_participation(
    participation_id: UUID,
    user=Depends(role_required(["customer"])),
    db: Session = Depends(get_db),
):
    referral_service.reconcile_for_user(db, user["id"])
    participation = (
        db.query(ReferralParticipation)
        .options(
            joinedload(ReferralParticipation.campaign),
            joinedload(ReferralParticipation.claim),
        )
        .filter(
            ReferralParticipation.id == participation_id,
            ReferralParticipation.user_id == user["id"],
        )
        .first()
    )
    if not participation:
        raise HTTPException(status_code=404, detail="Participation not found")
    return ok(
        referral_service.serialize_participation(db, participation),
        "Participation retrieved",
    )


@router.post("/participations/{participation_id}/spin")
def spin_wheel(
    participation_id: UUID,
    user=Depends(role_required(["customer"])),
    db: Session = Depends(get_db),
):
    system_settings_service.require_verified_email_for_user(
        db, user["id"], "claim a referral reward"
    )
    claim = referral_service.spin(db, participation_id, user["id"])
    return ok(claim, "Reward awarded")


@router.get("/claims/{claim_id}")
def get_claim(
    claim_id: UUID,
    user=Depends(role_required(["customer"])),
    db: Session = Depends(get_db),
):
    claim = referral_service.get_claim_for_user(db, claim_id, user["id"])
    return ok(referral_service.serialize_claim(db, claim), "Reward retrieved")


@router.get("/claims/{claim_id}/delivery-quote")
def delivery_quote(
    claim_id: UUID,
    address_id: UUID = Query(...),
    user=Depends(role_required(["customer"])),
    db: Session = Depends(get_db),
):
    claim = referral_service.get_claim_for_user(db, claim_id, user["id"])
    address = (
        db.query(Address)
        .options(joinedload(Address.delivery_state))
        .filter(Address.id == address_id, Address.user_id == user["id"])
        .first()
    )
    if not address:
        raise HTTPException(status_code=404, detail="Delivery address not found")
    if not claim.campaign or not claim.campaign.customer_pays_delivery:
        return ok({"delivery_fee": 0.0, "customer_pays_delivery": False})
    fee = resolve_delivery_fee(db, address)
    return ok(
        {
            "delivery_fee": float(Decimal(str(fee))),
            "customer_pays_delivery": True,
        }
    )


@router.post("/claims/{claim_id}/order")
def create_reward_order(
    claim_id: UUID,
    payload: ReferralOrderCreate,
    user=Depends(role_required(["customer"])),
    db: Session = Depends(get_db),
):
    system_settings_service.require_verified_email_for_user(
        db, user["id"], "place a reward order"
    )
    result = referral_service.create_reward_order(
        db, claim_id, user["id"], payload.address_id
    )
    order = result["order"]
    return ok(
        {
            "claim": result["claim"],
            "order": _order_summary(order),
        },
        "Reward order created",
    )
