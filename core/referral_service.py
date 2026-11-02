"""Referral campaign business logic.

Design notes:
- Attribution is recorded at registration but only counts after email
  verification (Google signups are verified by Google and confirmed at once).
- Progress is always derived from confirmed referral rows, never a mutable
  counter, so a failed hook or retry cannot leave the campaign out of sync.
- Wheel draws and reward orders are guarded by row locks plus database
  uniqueness constraints, making duplicated submissions safe.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional

from fastapi import HTTPException, status
from sqlalchemy import func, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from core.config import settings
from core.delivery_service import resolve_delivery_fee
from core.model import (
    Address,
    Notification,
    Order,
    OrderItem,
    Product,
    Referral,
    ReferralCampaign,
    ReferralCampaignProduct,
    ReferralEvent,
    ReferralParticipation,
    ReferralRewardClaim,
    User,
)

logger = logging.getLogger(__name__)

CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
CODE_LENGTH = 10


def utcnow() -> datetime:
    return datetime.utcnow()


def campaign_effective_status(
    campaign: ReferralCampaign, now: Optional[datetime] = None
) -> str:
    """scheduled | active | completed | inactive (derived, never stored)."""
    now = now or utcnow()
    if campaign.ended_at or (campaign.end_at and campaign.end_at <= now):
        return "completed"
    if not campaign.is_active:
        return "inactive"
    if campaign.start_at and campaign.start_at > now:
        return "scheduled"
    return "active"


def registration_window_open(
    campaign: ReferralCampaign, at: Optional[datetime] = None
) -> bool:
    """Whether a registration at ``at`` could earn credit for this campaign.

    Used both when attaching a signup and when confirming it later, so a code
    that was valid at signup keeps its validity even if verification happens
    after the campaign closes.
    """
    at = at or utcnow()
    if not campaign.is_active:
        return False
    if campaign.ended_at:
        return False
    if campaign.start_at and at < campaign.start_at:
        return False
    if campaign.end_at and at > campaign.end_at:
        return False
    return True


def mask_email(email: Optional[str]) -> str:
    if not email or "@" not in email:
        return "***"
    local, domain = email.split("@", 1)
    return f"{local[:1]}***@{domain}"


def _product_image(product: Product) -> Optional[str]:
    try:
        images = product.images or []
        return images[0].image_url if images else None
    except Exception:
        return None


def serialize_product(product: Product, display_order: int = 0) -> Dict[str, Any]:
    return {
        "product_id": str(product.id),
        "name": product.name,
        "price": float(product.price or 0),
        "image_url": _product_image(product),
        "stock_quantity": int(product.stock_quantity or 0),
        "status": product.status,
        "display_order": display_order,
        "available": product.status == "active"
        and int(product.stock_quantity or 0) > 0,
    }


class ReferralService:
    # ---------------- codes / devices ---------------- #

    def generate_code(self, db: Session) -> str:
        for _ in range(20):
            code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))
            exists = (
                db.query(ReferralParticipation.id)
                .filter(ReferralParticipation.referral_code == code)
                .first()
            )
            if not exists:
                return code
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not generate a referral code. Please try again.",
        )

    def _secret(self) -> str:
        return getattr(settings, "REFERRAL_HASH_SECRET", None) or settings.SECRET_KEY

    def hash_device(self, device_id: Optional[str]) -> Optional[str]:
        if not device_id:
            return None
        value = str(device_id).strip()
        if not value:
            return None
        return hmac.new(
            self._secret().encode(), value.encode(), hashlib.sha256
        ).hexdigest()

    def hash_ip(self, ip: Optional[str]) -> Optional[str]:
        if not ip:
            return None
        value = str(ip).strip()
        if not value:
            return None
        return hmac.new(
            self._secret().encode(), f"ip:{value}".encode(), hashlib.sha256
        ).hexdigest()

    def _advisory_lock(self, db: Session, key: str) -> None:
        """Serialize device-cap decisions across workers (Postgres only)."""
        try:
            if db.bind is not None and db.bind.dialect.name == "postgresql":
                db.execute(
                    text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
                    {"key": key},
                )
        except Exception as exc:  # never break verification on lock failure
            logger.warning("Referral advisory lock unavailable: %s", exc)

    # ---------------- serialization ---------------- #

    def campaign_reward_products(
        self, db: Session, campaign_id
    ) -> List[ReferralCampaignProduct]:
        return (
            db.query(ReferralCampaignProduct)
            .options(
                joinedload(ReferralCampaignProduct.product).joinedload(Product.images)
            )
            .filter(ReferralCampaignProduct.campaign_id == campaign_id)
            .order_by(
                ReferralCampaignProduct.display_order.asc(),
                ReferralCampaignProduct.created_at.asc(),
            )
            .all()
        )

    def serialize_campaign(
        self,
        campaign: ReferralCampaign,
        db: Optional[Session] = None,
        include_products: bool = True,
    ) -> Dict[str, Any]:
        products: List[Dict[str, Any]] = []
        if include_products and db is not None:
            products = [
                serialize_product(link.product, link.display_order or idx)
                for idx, link in enumerate(
                    self.campaign_reward_products(db, campaign.id)
                )
            ]
        return {
            "id": str(campaign.id),
            "name": campaign.name,
            "description": campaign.description,
            "required_referrals": campaign.required_referrals,
            "start_at": campaign.start_at.isoformat() if campaign.start_at else None,
            "end_at": campaign.end_at.isoformat() if campaign.end_at else None,
            "is_active": bool(campaign.is_active),
            "status": campaign_effective_status(campaign),
            "customer_pays_delivery": bool(campaign.customer_pays_delivery),
            "terms_locked": campaign.terms_locked_at is not None,
            "terms_locked_at": (
                campaign.terms_locked_at.isoformat()
                if campaign.terms_locked_at
                else None
            ),
            "max_credited_referrals_per_device": campaign.max_credited_referrals_per_device,
            "reward_products": products,
        }

    def campaign_stats(self, db: Session, campaign_id) -> Dict[str, int]:
        participants = (
            db.query(func.count(ReferralParticipation.id))
            .filter(ReferralParticipation.campaign_id == campaign_id)
            .scalar()
            or 0
        )
        qualified = (
            db.query(func.count(ReferralParticipation.id))
            .filter(
                ReferralParticipation.campaign_id == campaign_id,
                ReferralParticipation.status.in_(("qualified", "rewarded")),
            )
            .scalar()
            or 0
        )
        claims = (
            db.query(func.count(ReferralRewardClaim.id))
            .filter(ReferralRewardClaim.campaign_id == campaign_id)
            .scalar()
            or 0
        )
        reward_orders = (
            db.query(func.count(Order.id))
            .join(
                ReferralRewardClaim,
                Order.referral_claim_id == ReferralRewardClaim.id,
            )
            .filter(ReferralRewardClaim.campaign_id == campaign_id)
            .scalar()
            or 0
        )
        return {
            "participants": int(participants),
            "qualified": int(qualified),
            "claims": int(claims),
            "reward_orders": int(reward_orders),
        }

    def confirmed_count(self, db: Session, participation_id) -> int:
        return int(
            db.query(func.count(Referral.id))
            .filter(
                Referral.participation_id == participation_id,
                Referral.status == "confirmed",
            )
            .scalar()
            or 0
        )

    def _claim_order(self, db: Session, claim_id) -> Optional[Order]:
        return (
            db.query(Order)
            .options(
                joinedload(Order.order_items).joinedload(OrderItem.product),
                joinedload(Order.delivery_addr),
            )
            .filter(Order.referral_claim_id == claim_id)
            .first()
        )

    def serialize_claim(
        self, db: Session, claim: ReferralRewardClaim
    ) -> Dict[str, Any]:
        campaign = claim.campaign
        participation = claim.participation
        order = self._claim_order(db, claim.id)
        won_product = None
        if claim.won_product_id:
            product = db.query(Product).filter(Product.id == claim.won_product_id).first()
            if product:
                won_product = serialize_product(product)
        return {
            "id": str(claim.id),
            "participation_id": str(claim.participation_id),
            "campaign_id": str(claim.campaign_id),
            "status": claim.status,
            "won_product": won_product,
            "wheel": claim.wheel_snapshot or [],
            "segment_index": claim.segment_index,
            "awarded_at": claim.awarded_at.isoformat() if claim.awarded_at else None,
            "customer_pays_delivery": bool(
                getattr(campaign, "customer_pays_delivery", False)
            ),
            "order": (
                {
                    "id": str(order.id),
                    "status": order.status,
                    "total_amount": float(order.total_amount or 0),
                    "delivery_fee": float(order.delivery_fee or 0),
                    "delivery_address_id": (
                        str(order.delivery_address) if order.delivery_address else None
                    ),
                    "created_at": (
                        order.created_at.isoformat() if order.created_at else None
                    ),
                }
                if order
                else None
            ),
            "payment_required": bool(order and float(order.total_amount or 0) > 0),
            "participation_status": getattr(participation, "status", None),
        }

    def serialize_participation(
        self, db: Session, participation: ReferralParticipation
    ) -> Dict[str, Any]:
        campaign = participation.campaign
        referrals = (
            db.query(Referral)
            .options(joinedload(Referral.referred))
            .filter(Referral.participation_id == participation.id)
            .order_by(Referral.registered_at.desc())
            .all()
        )
        confirmed = sum(1 for r in referrals if r.status == "confirmed")
        claim = participation.claim
        return {
            "id": str(participation.id),
            "campaign_id": str(participation.campaign_id),
            "campaign": self.serialize_campaign(campaign, db, include_products=True),
            "referral_code": participation.referral_code,
            "status": participation.status,
            "qualified_at": (
                participation.qualified_at.isoformat()
                if participation.qualified_at
                else None
            ),
            "created_at": (
                participation.created_at.isoformat()
                if participation.created_at
                else None
            ),
            "confirmed_referrals": confirmed,
            "required_referrals": campaign.required_referrals,
            "remaining_referrals": max(0, campaign.required_referrals - confirmed),
            "referrals": [
                {
                    "id": str(r.id),
                    "email": mask_email(r.referred.email if r.referred else None),
                    "status": r.status,
                    "rejection_reason": r.rejection_reason,
                    "registered_at": (
                        r.registered_at.isoformat() if r.registered_at else None
                    ),
                    "confirmed_at": (
                        r.confirmed_at.isoformat() if r.confirmed_at else None
                    ),
                }
                for r in referrals
            ],
            "claim": self.serialize_claim(db, claim) if claim else None,
        }

    # ---------------- customer: join / list ---------------- #

    def list_available_campaigns(
        self, db: Session, user_id
    ) -> List[Dict[str, Any]]:
        now = utcnow()
        campaigns = (
            db.query(ReferralCampaign)
            .filter(
                ReferralCampaign.is_active.is_(True),
                ReferralCampaign.ended_at.is_(None),
                ReferralCampaign.start_at <= now,
                ReferralCampaign.end_at >= now,
            )
            .order_by(ReferralCampaign.end_at.asc())
            .all()
        )
        participations = {
            p.campaign_id: p
            for p in db.query(ReferralParticipation)
            .filter(ReferralParticipation.user_id == user_id)
            .all()
        }
        result = []
        for campaign in campaigns:
            participation = participations.get(campaign.id)
            item = self.serialize_campaign(campaign, db)
            item["joined"] = participation is not None
            item["participation"] = (
                self.serialize_participation(db, participation)
                if participation
                else None
            )
            result.append(item)
        return result

    def join_campaign(self, db: Session, campaign_id, user_id) -> ReferralParticipation:
        campaign = (
            db.query(ReferralCampaign)
            .filter(ReferralCampaign.id == campaign_id)
            .with_for_update()
            .first()
        )
        if not campaign:
            raise HTTPException(status_code=404, detail="Campaign not found")
        if campaign_effective_status(campaign) != "active":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="This referral campaign is not currently active",
            )

        existing = (
            db.query(ReferralParticipation)
            .filter(
                ReferralParticipation.campaign_id == campaign.id,
                ReferralParticipation.user_id == user_id,
            )
            .first()
        )
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="You have already joined this campaign",
            )

        participation = ReferralParticipation(
            campaign_id=campaign.id,
            user_id=user_id,
            referral_code=self.generate_code(db),
            status="active",
        )
        try:
            with db.begin_nested():
                db.add(participation)
                db.flush()
        except IntegrityError:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="You have already joined this campaign",
            )

        self.log_event(
            db,
            "participation_joined",
            campaign_id=campaign.id,
            participation_id=participation.id,
            actor_user_id=user_id,
        )
        db.commit()
        db.refresh(participation)
        return participation

    # ---------------- registration attribution ---------------- #

    def attach_registration(
        self,
        db: Session,
        referred_user_id,
        code: Optional[str],
        device_id: Optional[str] = None,
        client_ip: Optional[str] = None,
    ) -> Optional[Referral]:
        """Record a pending attribution inside the registration transaction.

        Never raises: an invalid, expired or duplicate code must not break
        account creation. The caller owns the transaction/commit.
        """
        if not code:
            return None
        normalized = str(code).strip().upper()
        if not normalized:
            return None

        try:
            participation = (
                db.query(ReferralParticipation)
                .options(joinedload(ReferralParticipation.campaign))
                .filter(ReferralParticipation.referral_code == normalized)
                .first()
            )
            if not participation:
                return None
            campaign = participation.campaign
            if not campaign or not registration_window_open(campaign, utcnow()):
                return None
            if str(participation.user_id) == str(referred_user_id):
                return None
            existing = (
                db.query(Referral.id)
                .filter(Referral.referred_user_id == referred_user_id)
                .first()
            )
            if existing:
                return None

            referral = Referral(
                participation_id=participation.id,
                campaign_id=campaign.id,
                referrer_user_id=participation.user_id,
                referred_user_id=referred_user_id,
                code_used=normalized,
                status="pending",
                device_hash=self.hash_device(device_id),
                signup_ip_hash=self.hash_ip(client_ip),
                registered_at=utcnow(),
            )
            with db.begin_nested():
                db.add(referral)
                db.flush()
            self.log_event(
                db,
                "referral_attributed",
                campaign_id=campaign.id,
                participation_id=participation.id,
                referral_id=referral.id,
                actor_user_id=referred_user_id,
            )
            return referral
        except IntegrityError:
            # Unique referred-user constraint: someone already got credit.
            return None
        except Exception as exc:
            logger.warning("Referral attribution skipped: %s", exc)
            return None

    def confirm_for_user(self, db: Session, referred_user_id) -> Optional[Referral]:
        """Confirm the user's pending referral after email verification.

        Best-effort: exceptions are logged and rolled back so email
        verification itself always succeeds. A later dashboard load retries
        via ``reconcile_for_user``.
        """
        try:
            referral = (
                db.query(Referral)
                .filter(
                    Referral.referred_user_id == referred_user_id,
                    Referral.status == "pending",
                )
                .first()
            )
            if not referral:
                return None

            user = db.query(User).filter(User.id == referred_user_id).first()
            if not user or not user.email_verified:
                return None

            participation = (
                db.query(ReferralParticipation)
                .filter(ReferralParticipation.id == referral.participation_id)
                .with_for_update()
                .first()
            )
            referral = (
                db.query(Referral)
                .filter(Referral.id == referral.id)
                .with_for_update()
                .first()
            )
            if not participation or not referral or referral.status != "pending":
                db.rollback()
                return referral

            campaign = (
                db.query(ReferralCampaign)
                .filter(ReferralCampaign.id == referral.campaign_id)
                .first()
            )
            if not campaign:
                referral.status = "rejected"
                referral.rejection_reason = "campaign_deleted"
                db.commit()
                return referral

            if not self._registered_inside_window(campaign, referral.registered_at):
                self._reject(db, referral, "campaign_expired")
                db.commit()
                return referral

            if str(referral.referrer_user_id) == str(referral.referred_user_id):
                self._reject(db, referral, "self_referral")
                db.commit()
                return referral

            if self._device_limit_reached(db, referral, campaign):
                self._reject(db, referral, "device_limit")
                db.commit()
                return referral

            referral.status = "confirmed"
            referral.confirmed_at = utcnow()
            self.log_event(
                db,
                "referral_confirmed",
                campaign_id=campaign.id,
                participation_id=participation.id,
                referral_id=referral.id,
                actor_user_id=referred_user_id,
            )
            newly_qualified = self._revalidate_participation(db, participation)
            db.commit()

            self._notify_referral_confirmed(db, referral, campaign)
            if newly_qualified:
                self._notify_qualified(db, participation, campaign)
            return referral
        except Exception as exc:
            db.rollback()
            logger.warning("Referral confirmation deferred for %s: %s", referred_user_id, exc)
            return None

    def reconcile_for_user(self, db: Session, user_id) -> None:
        """Heal attribution/qualification gaps when the customer views referrals."""
        try:
            pending = (
                db.query(Referral)
                .filter(
                    Referral.referred_user_id == user_id,
                    Referral.status == "pending",
                )
                .first()
            )
            if pending:
                self.confirm_for_user(db, user_id)

            participations = (
                db.query(ReferralParticipation)
                .filter(ReferralParticipation.user_id == user_id)
                .all()
            )
            changed = False
            for participation in participations:
                if participation.status in ("active", "qualified"):
                    locked = (
                        db.query(ReferralParticipation)
                        .filter(ReferralParticipation.id == participation.id)
                        .with_for_update()
                        .first()
                    )
                    if locked and self._revalidate_participation(db, locked):
                        changed = True
            if changed:
                db.commit()
        except Exception as exc:
            db.rollback()
            logger.warning("Referral reconciliation skipped for %s: %s", user_id, exc)

    def _registered_inside_window(
        self, campaign: ReferralCampaign, registered_at: Optional[datetime]
    ) -> bool:
        if not registered_at:
            return False
        if campaign.start_at and registered_at < campaign.start_at:
            return False
        if campaign.end_at and registered_at > campaign.end_at:
            return False
        return True

    def _device_limit_reached(
        self, db: Session, referral: Referral, campaign: ReferralCampaign
    ) -> bool:
        if not referral.device_hash:
            return False
        cap = int(campaign.max_credited_referrals_per_device or 1)
        if cap <= 0:
            return True
        self._advisory_lock(
            db, f"referral-device:{campaign.id}:{referral.device_hash}"
        )
        used = (
            db.query(func.count(Referral.id))
            .filter(
                Referral.campaign_id == campaign.id,
                Referral.device_hash == referral.device_hash,
                Referral.status == "confirmed",
                Referral.id != referral.id,
            )
            .scalar()
            or 0
        )
        return int(used) >= cap

    def _reject(self, db: Session, referral: Referral, reason: str) -> None:
        referral.status = "rejected"
        referral.rejection_reason = reason
        self.log_event(
            db,
            "referral_rejected",
            campaign_id=referral.campaign_id,
            participation_id=referral.participation_id,
            referral_id=referral.id,
            actor_user_id=referral.referred_user_id,
            details={"reason": reason},
        )

    def _revalidate_participation(
        self, db: Session, participation: ReferralParticipation
    ) -> bool:
        """Recompute progress and qualify if the target is reached.

        Returns True only on the active -> qualified transition.
        """
        if participation.status in ("rewarded", "cancelled"):
            return False

        confirmed = self.confirmed_count(db, participation.id)
        required = max(1, int(participation.campaign.required_referrals or 1))
        if confirmed < required:
            return False

        newly_qualified = participation.status == "active"
        if newly_qualified:
            participation.status = "qualified"
            participation.qualified_at = utcnow()
            self.log_event(
                db,
                "participation_qualified",
                campaign_id=participation.campaign_id,
                participation_id=participation.id,
                actor_user_id=participation.user_id,
            )
        self._ensure_claim(db, participation)
        return newly_qualified

    def _ensure_claim(
        self, db: Session, participation: ReferralParticipation
    ) -> Optional[ReferralRewardClaim]:
        existing = (
            db.query(ReferralRewardClaim)
            .filter(ReferralRewardClaim.participation_id == participation.id)
            .first()
        )
        if existing:
            return existing
        claim = ReferralRewardClaim(
            participation_id=participation.id,
            campaign_id=participation.campaign_id,
            status="unlocked",
        )
        try:
            with db.begin_nested():
                db.add(claim)
                db.flush()
        except IntegrityError:
            return (
                db.query(ReferralRewardClaim)
                .filter(ReferralRewardClaim.participation_id == participation.id)
                .first()
            )
        return claim

    # ---------------- wheel / reward ---------------- #

    def get_claim_for_user(
        self, db: Session, participation_id, user_id
    ) -> ReferralRewardClaim:
        claim = (
            db.query(ReferralRewardClaim)
            .join(
                ReferralParticipation,
                ReferralRewardClaim.participation_id == ReferralParticipation.id,
            )
            .filter(
                ReferralRewardClaim.participation_id == participation_id,
                ReferralParticipation.user_id == user_id,
            )
            .first()
        )
        if not claim:
            raise HTTPException(status_code=404, detail="Reward not found")
        return claim

    def spin(
        self, db: Session, participation_id, user_id
    ) -> Dict[str, Any]:
        participation = (
            db.query(ReferralParticipation)
            .filter(
                ReferralParticipation.id == participation_id,
                ReferralParticipation.user_id == user_id,
            )
            .with_for_update()
            .first()
        )
        if not participation:
            raise HTTPException(status_code=404, detail="Participation not found")
        if participation.status not in ("qualified", "rewarded"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You have not qualified for this reward yet",
            )

        claim = (
            db.query(ReferralRewardClaim)
            .filter(ReferralRewardClaim.participation_id == participation.id)
            .with_for_update()
            .first()
        )
        if not claim:
            claim = self._ensure_claim(db, participation)
            if not claim:
                raise HTTPException(status_code=500, detail="Could not create reward claim")

        if claim.status in ("awarded", "order_created", "fulfilled"):
            return self.serialize_claim(db, claim)
        if claim.status == "cancelled":
            raise HTTPException(status_code=409, detail="This reward is no longer available")

        links = self.campaign_reward_products(db, participation.campaign_id)
        if not links:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This campaign has no reward products configured",
            )
        wheel = []
        eligible: List[int] = []
        for idx, link in enumerate(links):
            item = serialize_product(link.product, idx)
            wheel.append(item)
            if item["available"]:
                eligible.append(idx)
        if not eligible:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "Reward products are temporarily out of stock. "
                    "Please contact support."
                ),
            )

        segment_index = eligible[secrets.randbelow(len(eligible))]
        chosen = links[segment_index].product
        claim.status = "awarded"
        claim.won_product_id = chosen.id
        claim.wheel_snapshot = wheel
        claim.segment_index = segment_index
        claim.draw_nonce = secrets.token_hex(16)
        claim.awarded_at = utcnow()
        participation.status = "rewarded"
        self.log_event(
            db,
            "reward_awarded",
            campaign_id=participation.campaign_id,
            participation_id=participation.id,
            claim_id=claim.id,
            actor_user_id=user_id,
            details={
                "product_id": str(chosen.id),
                "segment_index": segment_index,
                "eligible_segments": eligible,
            },
        )
        db.commit()
        db.refresh(claim)
        self._notify_awarded(db, participation, claim)
        return self.serialize_claim(db, claim)

    def create_reward_order(
        self, db: Session, claim_id, user_id, address_id
    ) -> Dict[str, Any]:
        claim = (
            db.query(ReferralRewardClaim)
            .filter(ReferralRewardClaim.id == claim_id)
            .with_for_update()
            .first()
        )
        if not claim:
            raise HTTPException(status_code=404, detail="Reward not found")
        participation = (
            db.query(ReferralParticipation)
            .filter(ReferralParticipation.id == claim.participation_id)
            .first()
        )
        if not participation or str(participation.user_id) != str(user_id):
            raise HTTPException(status_code=404, detail="Reward not found")

        existing = self._claim_order(db, claim.id)
        if existing:
            return {"claim": self.serialize_claim(db, claim), "order": existing}

        if claim.status != "awarded" or not claim.won_product_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Spin the wheel before creating the reward order",
            )

        address = (
            db.query(Address)
            .options(joinedload(Address.delivery_state))
            .filter(Address.id == address_id, Address.user_id == user_id)
            .first()
        )
        if not address:
            raise HTTPException(status_code=404, detail="Delivery address not found")

        product = (
            db.query(Product)
            .filter(Product.id == claim.won_product_id)
            .with_for_update()
            .first()
        )
        if not product:
            raise HTTPException(status_code=409, detail="Reward product no longer exists")
        if product.status != "active" or int(product.stock_quantity or 0) < 1:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This reward product is temporarily out of stock",
            )

        campaign = claim.campaign
        delivery_fee = Decimal("0.00")
        if campaign and campaign.customer_pays_delivery:
            delivery_fee = resolve_delivery_fee(db, address)

        order_status = "processing" if delivery_fee <= 0 else "pending"
        order = Order(
            buyer_id=user_id,
            total_amount=delivery_fee,
            status=order_status,
            delivery_address=address.id,
            delivery_type="delivery",
            delivery_fee=delivery_fee,
            estimated_delivery_date=utcnow() + timedelta(days=7),
            order_type="referral_reward",
            referral_claim_id=claim.id,
        )
        db.add(order)
        db.flush()

        db.add(
            OrderItem(
                order_id=order.id,
                product_id=product.id,
                quantity=1,
                price=0,
                status=order_status,
            )
        )

        product.stock_quantity = int(product.stock_quantity or 0) - 1
        if product.stock_quantity == 0:
            product.status = "out_of_stock"

        claim.status = "order_created"
        self.log_event(
            db,
            "reward_order_created",
            campaign_id=claim.campaign_id,
            participation_id=participation.id,
            claim_id=claim.id,
            actor_user_id=user_id,
            details={
                "order_id": str(order.id),
                "delivery_fee": float(delivery_fee),
                "customer_pays_delivery": bool(
                    campaign.customer_pays_delivery if campaign else False
                ),
            },
        )
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            existing = self._claim_order(db, claim.id)
            if existing:
                return {"claim": self.serialize_claim(db, claim), "order": existing}
            raise
        db.refresh(order)
        self._notify_order_created(db, participation, claim, order)
        return {"claim": self.serialize_claim(db, claim), "order": order}

    # ---------------- admin review ---------------- #

    def approve_rejected_referral(
        self, db: Session, referral_id, admin_id
    ) -> Referral:
        referral = (
            db.query(Referral)
            .filter(Referral.id == referral_id)
            .with_for_update()
            .first()
        )
        if not referral:
            raise HTTPException(status_code=404, detail="Referral not found")
        if referral.status != "rejected":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Only rejected referrals can be approved",
            )
        campaign = (
            db.query(ReferralCampaign)
            .filter(ReferralCampaign.id == referral.campaign_id)
            .first()
        )
        if not campaign:
            raise HTTPException(status_code=404, detail="Campaign not found")
        if not self._registered_inside_window(campaign, referral.registered_at):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="The registration fell outside the campaign window",
            )

        participation = (
            db.query(ReferralParticipation)
            .filter(ReferralParticipation.id == referral.participation_id)
            .with_for_update()
            .first()
        )
        referral.status = "confirmed"
        referral.confirmed_at = utcnow()
        referral.rejection_reason = None
        self.log_event(
            db,
            "referral_manually_approved",
            campaign_id=campaign.id,
            participation_id=participation.id if participation else None,
            referral_id=referral.id,
            actor_user_id=admin_id,
        )
        newly_qualified = (
            self._revalidate_participation(db, participation)
            if participation
            else False
        )
        db.commit()
        db.refresh(referral)
        if participation:
            self._notify_referral_confirmed(db, referral, campaign)
            if newly_qualified:
                self._notify_qualified(db, participation, campaign)
        return referral

    # ---------------- events / notifications ---------------- #

    def log_event(
        self,
        db: Session,
        event: str,
        campaign_id=None,
        participation_id=None,
        referral_id=None,
        claim_id=None,
        actor_user_id=None,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        try:
            db.add(
                ReferralEvent(
                    event=event,
                    campaign_id=campaign_id,
                    participation_id=participation_id,
                    referral_id=referral_id,
                    claim_id=claim_id,
                    actor_user_id=actor_user_id,
                    details=details,
                )
            )
            db.flush()
        except Exception as exc:
            logger.warning("Could not write referral event %s: %s", event, exc)

    def _notify(
        self,
        db: Session,
        user_id,
        notification_type: str,
        title: str,
        message: str,
        data: Optional[Dict[str, Any]] = None,
    ) -> None:
        try:
            from core.notifications_service import create_notification

            create_notification(
                db,
                {
                    "user_id": str(user_id),
                    "type": notification_type,
                    "title": title,
                    "message": message,
                    "priority": "high",
                    "channels": ["in_app", "email"],
                    "data": data or {},
                },
            )
        except Exception as exc:
            logger.warning("Referral notification failed: %s", exc)

    def _notify_referral_confirmed(
        self, db: Session, referral: Referral, campaign: ReferralCampaign
    ) -> None:
        self._notify(
            db,
            referral.referrer_user_id,
            "referral_confirmed",
            "Referral confirmed",
            f"A new customer verified their email through your link for "
            f"“{campaign.name}”. Your progress has been updated.",
            {"campaign_id": str(campaign.id), "referral_id": str(referral.id)},
        )

    def _notify_qualified(
        self,
        db: Session,
        participation: ReferralParticipation,
        campaign: ReferralCampaign,
    ) -> None:
        self._notify(
            db,
            participation.user_id,
            "referral_qualified",
            "You unlocked your reward!",
            f"You reached {campaign.required_referrals} verified referrals in "
            f"“{campaign.name}”. Spin the wheel to claim your reward.",
            {
                "campaign_id": str(campaign.id),
                "participation_id": str(participation.id),
            },
        )

    def _notify_awarded(
        self,
        db: Session,
        participation: ReferralParticipation,
        claim: ReferralRewardClaim,
    ) -> None:
        product = claim.won_product
        self._notify(
            db,
            participation.user_id,
            "referral_reward_awarded",
            "Your reward is ready",
            f"You won {product.name if product else 'a reward'}. "
            "Choose a delivery address to place your free reward order.",
            {
                "campaign_id": str(claim.campaign_id),
                "claim_id": str(claim.id),
            },
        )

    def _notify_order_created(
        self,
        db: Session,
        participation: ReferralParticipation,
        claim: ReferralRewardClaim,
        order: Order,
    ) -> None:
        self._notify(
            db,
            participation.user_id,
            "referral_order_created",
            "Reward order created",
            f"Your free reward order #{str(order.id)[:8]} has been created. "
            "Our team will process it shortly.",
            {
                "campaign_id": str(claim.campaign_id),
                "claim_id": str(claim.id),
                "order_id": str(order.id),
            },
        )


referral_service = ReferralService()
