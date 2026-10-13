"""Total (unblocked) hard-delete for user accounts.

WARNING: this permanently removes the user row AND all linked rows,
including financial ledgers (orders, payments, agreements). The caller
(admin endpoint) must confirm explicitly; an AuditLog entry is written
BEFORE deletion so there is a paper trail of who deleted whom.

Deletion order respects FK constraints (children first, parents last).
Bulk ORM deletes (query.delete) are avoided where cascade relationships
exist; rows are deleted via ORM objects so cascades fire.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List
from uuid import UUID

from sqlalchemy.orm import Session

from core.logging_config import get_logger

logger = get_logger("services.user_deletion")


def deletion_preview(db: Session, user_id: str) -> Dict[str, Any]:
    """Count rows that would be removed by hard_delete_user (no writes)."""
    from core.model import (
        Address,
        Dispute,
        FinancingApplication,
        GeneralAgreement,
        GeneralInspection,
        Notification,
        NotificationPreferences,
        Order,
        Payment,
        PaymentMandate,
        Profile,
        PushDeviceToken,
        Review,
        Stats,
        User,
        Wishlist,
    )

    uid = user_id
    user = db.query(User).filter(User.id == uid).first()
    if not user:
        return {"exists": False}
    orders = db.query(Order).filter(Order.buyer_id == uid).all()
    order_ids = [o.id for o in orders]
    return {
        "exists": True,
        "email": user.email,
        "role": user.role,
        "email_verified": user.email_verified,
        "is_active": getattr(user, "is_active", True),
        "created_at": user.created_at.isoformat() if user.created_at else None,
        "last_login": user.last_login.isoformat() if user.last_login else None,
        "counts": {
            "orders": len(orders),
            "order_items": sum(len(o.order_items) for o in orders),
            "payments": db.query(Payment).filter(Payment.buyer_id == uid).count(),
            "agreements": db.query(GeneralAgreement).filter(GeneralAgreement.user_id == uid).count(),
            "inspections": db.query(GeneralInspection).filter(GeneralInspection.user_id == uid).count(),
            "mandates": db.query(PaymentMandate).filter(PaymentMandate.user_id == uid).count(),
            "disputes": db.query(Dispute).filter(Dispute.user_id == uid).count(),
            "financing_applications": db.query(FinancingApplication).filter(FinancingApplication.user_id == uid).count(),
            "addresses": db.query(Address).filter(Address.user_id == uid).count(),
            "reviews": db.query(Review).filter(Review.user_id == uid).count(),
            "wishlists": db.query(Wishlist).filter(Wishlist.user_id == uid).count(),
            "notifications": db.query(Notification).filter(Notification.user_id == uid).count(),
            "notification_prefs": db.query(NotificationPreferences).filter(NotificationPreferences.user_id == uid).count(),
            "push_tokens": db.query(PushDeviceToken).filter(PushDeviceToken.user_id == uid).count(),
            "has_profile": db.query(Profile).filter(Profile.id == uid).count(),
            "has_stats": db.query(Stats).filter(Stats.user_id == uid).count(),
        },
        "order_ids_sample": [str(i) for i in order_ids[:5]],
    }


def hard_delete_user(db: Session, target_user_id: str, performed_by: Dict[str, Any]) -> Dict[str, Any]:
    """Permanently delete a user and every linked row. Returns preview + deleted email."""
    from core.model import (
        Address,
        AuditLog,
        Dispute,
        ExternalPayment,
        FinancingApplication,
        GeneralAgreement,
        GeneralInspection,
        Notification,
        NotificationPreferences,
        Order,
        Payment,
        PaymentMandate,
        Profile,
        PushDeviceToken,
        Review,
        Stats,
        SystemSettings,
        User,
        Wishlist,
    )

    target = db.query(User).filter(User.id == target_user_id).first()
    if not target:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="User not found")
    if target.role == "admin":
        from fastapi import HTTPException

        raise HTTPException(status_code=400, detail="Admin accounts cannot be hard-deleted. Demote or lock instead.")
    if str(target.id) == str(performed_by.get("id")):
        from fastapi import HTTPException

        raise HTTPException(status_code=400, detail="You cannot delete your own account.")

    uid = target.id
    preview = deletion_preview(db, uid)

    # Paper trail BEFORE the rows vanish.
    try:
        db.add(
            AuditLog(
                admin_id=performed_by["id"],
                target_id=uid,
                action="user_hard_deleted",
                details=(
                    f"Total delete of {preview.get('email')} "
                    f"(role={preview.get('role')}, verified={preview.get('email_verified')}) "
                    f"counts={preview.get('counts')}"
                ),
            )
        )
        db.flush()
    except Exception as e:
        logger.warning(f"AuditLog write failed before hard-delete of {uid}: {e}")

    try:
        # 1. Messaging / device rows (User FK)
        db.query(PushDeviceToken).filter(PushDeviceToken.user_id == uid).delete(synchronize_session=False)
        db.query(NotificationPreferences).filter(NotificationPreferences.user_id == uid).delete(synchronize_session=False)
        db.query(Notification).filter(Notification.user_id == uid).delete(synchronize_session=False)

        # 2. Mandates + disputes (reference agreements/orders; remove first)
        db.query(PaymentMandate).filter(PaymentMandate.user_id == uid).delete(synchronize_session=False)
        db.query(Dispute).filter(Dispute.user_id == uid).delete(synchronize_session=False)

        # 3. Payments (buyer FK; includes order + agreement payments)
        db.query(Payment).filter(Payment.buyer_id == uid).delete(synchronize_session=False)

        # 4. Orders via ORM so OrderItems cascade (order_items has delete-orphan).
        for order in db.query(Order).filter(Order.buyer_id == uid).all():
            db.delete(order)
        db.flush()

        # 5. Agreements then inspections (agreements may point at inspections).
        db.query(GeneralAgreement).filter(GeneralAgreement.user_id == uid).delete(synchronize_session=False)
        db.query(GeneralInspection).filter(GeneralInspection.user_id == uid).delete(synchronize_session=False)

        # 6. Financing applications (documents cascade delete-orphan).
        for app in db.query(FinancingApplication).filter(FinancingApplication.user_id == uid).all():
            db.delete(app)
        db.flush()

        # 7. Profile-linked rows.
        db.query(Address).filter(Address.user_id == uid).delete(synchronize_session=False)
        db.query(Review).filter(Review.user_id == uid).delete(synchronize_session=False)
        db.query(Wishlist).filter(Wishlist.user_id == uid).delete(synchronize_session=False)
        db.query(Stats).filter(Stats.user_id == uid).delete(synchronize_session=False)

        # 8. Unlink (do NOT delete store books): external offline sales keep their
        # rows but lose the buyer link; settings/reviews attribution nulled.
        db.query(ExternalPayment).filter(ExternalPayment.buyer_id == uid).update(
            {"buyer_id": None}, synchronize_session=False
        )
        db.query(SystemSettings).filter(SystemSettings.updated_by_user_id == uid).update(
            {"updated_by_user_id": None}, synchronize_session=False
        )
        db.query(FinancingApplication).filter(FinancingApplication.reviewed_by == uid).update(
            {"reviewed_by": None}, synchronize_session=False
        )
        db.query(FinancingApplication).filter(FinancingApplication.revoked_by == uid).update(
            {"revoked_by": None}, synchronize_session=False
        )
        # Prior audit entries keep their rows; retarget so the FK stays valid.
        db.query(AuditLog).filter(AuditLog.target_id == uid).update(
            {"target_id": None}, synchronize_session=False
        )

        # 9. Profile then user.
        db.query(Profile).filter(Profile.id == uid).delete(synchronize_session=False)
        db.query(User).filter(User.id == uid).delete(synchronize_session=False)

        db.commit()
    except Exception:
        db.rollback()
        raise

    logger.info(f"Hard-deleted user {uid} ({preview.get('email')}) by admin {performed_by.get('email')}")
    return {"deleted_email": preview.get("email"), "counts": preview.get("counts", {})}


def find_bot_candidates(
    db: Session, days: int = 7, limit: int = 100, unverified_only: bool = True
) -> List[Dict[str, Any]]:
    """List likely-bot accounts: recent, never logged in, no orders/payments.

    Used by the admin bulk-cleanup endpoint (dry-run by default).
    """
    from core.model import Order, Payment, User

    cutoff = datetime.utcnow() - timedelta(days=days)
    q = db.query(User).filter(User.role == "customer", User.created_at >= cutoff)
    if unverified_only:
        q = q.filter(User.email_verified.is_(False))
    q = q.filter(User.last_login.is_(None)).order_by(User.created_at.desc()).limit(limit)
    out: List[Dict[str, Any]] = []
    for u in q.all():
        has_orders = db.query(Order).filter(Order.buyer_id == u.id).count() > 0
        has_payments = db.query(Payment).filter(Payment.buyer_id == u.id).count() > 0
        if has_orders or has_payments:
            continue  # never bulk-delete paying customers
        out.append(
            {
                "id": str(u.id),
                "email": u.email,
                "created_at": u.created_at.isoformat() if u.created_at else None,
                "failed_login_attempts": u.failed_login_attempts,
            }
        )
    return out
