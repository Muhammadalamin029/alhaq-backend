from typing import Dict, Any, List, Optional, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import func, or_
from datetime import datetime
import json
import logging

from core.model import Notification, NotificationPreferences
# Removed circular import - email sending is handled separately
from core.email_service import email_service

logger = logging.getLogger(__name__)


# Canonical set of notification types that exist in the Postgres
# `notification_type` enum (see core/model.py + alembic migrations).
# Unknown types are mapped to a safe fallback BEFORE insert so a typo or a
# code-first type that missed its migration can never 500 a payment/order
# flow with InvalidTextRepresentation again.
VALID_NOTIFICATION_TYPES = frozenset({
    "order_confirmed",
    "order_processing",
    "order_shipped",
    "order_delivered",
    "order_cancelled",
    "payment_successful",
    "payment_failed",
    "payment_refunded",
    "account_verified",
    "password_changed",
    "profile_updated",
    "wishlist_item_back_in_stock",
    "system_announcement",
    "promotional_offer",
    "car_approved",
    "car_rejected",
    "inspection_scheduled",
    "inspection_confirmed",
    "inspection_rejected",
    "inspection_complete",
    "property_acquired",
    "agreement_created",
    "agreement_approved",
    "agreement_rejected",
    "agreement_activated",
    "agreement_completed",
    "agreement_update",
    "installment_paid",
    "payment_reminder",
    "installment_due",
    "installment_defaulted",
    "financing_application_submitted",
    "financing_application_approved",
    "financing_application_rejected",
    "financing_application_revoked",
})

# Best-effort fallback for types that predate their DB enum migration.
_NOTIFICATION_TYPE_FALLBACKS = {
    "agreement_activated": "agreement_update",
    "payment_refunded": "payment_failed",
}


def _coerce_notification_type(notification_type: str) -> str:
    if notification_type in VALID_NOTIFICATION_TYPES:
        return notification_type
    fallback = _NOTIFICATION_TYPE_FALLBACKS.get(notification_type, "system_announcement")
    logger.warning(
        f"Unknown notification type '{notification_type}' — falling back to '{fallback}'"
    )
    return fallback


def _get_user_contact_info(db: Session, user_id: str) -> tuple[Optional[str], str]:
    """Get user email address and name by user ID"""
    try:
        from core.model import User, Profile
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            return None, "User"

        name = "User"
        profile = db.query(Profile).filter(Profile.id == user_id).first()
        if profile:
            name = profile.name

        return user.email, name
    except Exception as e:
        logger.error(f"Failed to get user info for user_id {user_id}: {e}")
        return None, "User"


def _serialize_channels(channels: Optional[List[str]]) -> str:
    if not channels or len(channels) == 0:
        return "in_app"
    return ",".join(sorted(set(channels)))


def _parse_channels(channels_text: Optional[str]) -> List[str]:
    if not channels_text:
        return ["in_app"]
    return [c for c in channels_text.split(",") if c]


def _serialize_data(data: Optional[Dict[str, Any]]) -> Optional[str]:
    if data is None:
        return None
    return json.dumps(data)


def _parse_data(data_text: Optional[str]) -> Optional[Dict[str, Any]]:
    if not data_text:
        return None
    try:
        return json.loads(data_text)
    except Exception:
        return None


def create_notification(db: Session, payload: Dict[str, Any]) -> Notification:
    # When a dedicated transactional email is already queued for the same event,
    # callers set skip_email to keep this notification in-app only.
    skip_email = bool(payload.get("skip_email"))

    # Coerce unknown/forward-added types so the INSERT can never fail with
    # `invalid input value for enum notification_type` and take down the
    # calling flow (e.g. POST /payments/verify after the user already paid).
    notification_type = _coerce_notification_type(payload.get("type", "system_announcement"))

    # Include email by default, but never when the event is email-suppressed.
    req_channels = payload.get("channels") or []
    if not req_channels:
        req_channels = ["in_app", "email"]
    if skip_email:
        req_channels = [c for c in req_channels if c != "email"] or ["in_app"]
    elif "email" not in req_channels:
        req_channels.append("email")

    notification = Notification(
        user_id=payload["user_id"],
        type=notification_type,
        title=payload["title"],
        message=payload["message"],
        priority=payload.get("priority", "low"),
        channels=_serialize_channels(req_channels),
        data=_serialize_data(payload.get("data")),
        expires_at=payload.get("expires_at"),
    )
    db.add(notification)
    db.commit()
    db.refresh(notification)

    # Email dispatch logic
    channels = set(_parse_channels(notification.channels))
    type_to_group = {
        'order_confirmed': 'order_updates',
        'order_processing': 'order_updates',
        'order_shipped': 'order_updates',
        'order_delivered': 'order_updates',
        'order_cancelled': 'order_updates',
        'payment_successful': 'payment_updates',
        'payment_failed': 'payment_updates',
        'payment_refunded': 'payment_updates',
        'account_verified': 'account_updates',
        'password_changed': 'account_updates',
        'profile_updated': 'account_updates',
        'wishlist_item_back_in_stock': 'promotional_offers',
        'system_announcement': 'system_announcements',
        'promotional_offer': 'promotional_offers',
        'inspection_scheduled': 'order_updates',
        'inspection_confirmed': 'order_updates',
        'inspection_rejected': 'order_updates',
        'inspection_complete': 'order_updates',
        'agreement_update': 'order_updates',
        'agreement_created': 'order_updates',
        'agreement_approved': 'order_updates',
        'agreement_rejected': 'order_updates',
        'agreement_activated': 'order_updates',
        'agreement_completed': 'order_updates',
        'car_approved': 'order_updates',
        'car_rejected': 'order_updates',
        'property_acquired': 'order_updates',
        'installment_paid': 'payment_updates',
        'payment_reminder': 'payment_updates',
        'installment_due': 'payment_updates',
        'installment_defaulted': 'payment_updates',
    }
    group = type_to_group.get(notification.type, 'order_updates')
    if 'email' in channels and not skip_email:
        prefs = get_or_create_preferences(db, str(notification.user_id))
        allowed = bool(getattr(prefs, f"email_{group}", True)) # Default to True

        if allowed:
            # Get contact info (email and display name)
            to_email, user_name = _get_user_contact_info(db, str(notification.user_id))
            
            # Allow payload to override email if provided
            if payload.get('to_email'):
                to_email = payload.get('to_email')

            if to_email:
                try:
                    # Use professional email template
                    html_body, text_body = email_service.render_notification_email(
                        notification_type=notification.type,
                        title=notification.title,
                        message=notification.message,
                        user_name=user_name,
                        data=_parse_data(notification.data)
                    )

                    from core.tasks import send_notification_email
                    send_notification_email.delay(
                        to_email=to_email,
                        subject=notification.title,
                        html_body=html_body,
                        text_body=text_body
                    )
                    logger.info(f"Notification email queued for {to_email} via Celery")
                except Exception as e:
                    logger.error(f"Error queuing email for {to_email}: {e}")

    # Push dispatch: Expo push to the user's devices, respecting push_*
    # preferences. Fire-and-forget via Celery; never breaks notification save.
    try:
        push_prefs = get_or_create_preferences(db, str(notification.user_id))
        push_allowed = bool(getattr(push_prefs, f"push_{group}", True))
        if push_allowed:
            from core.tasks import send_push_notification
            send_push_notification.delay(
                user_id=str(notification.user_id),
                title=notification.title,
                message=notification.message,
                data={
                    "notification_id": str(notification.id),
                    "type": notification.type,
                    **(_parse_data(notification.data) or {}),
                },
            )
    except Exception as e:
        logger.error(f"Error queuing push for user {notification.user_id}: {e}")

    return notification


def get_notifications(
    db: Session,
    user_id: str,
    filters: Dict[str, Any],
) -> Tuple[List[Notification], Dict[str, int], int]:
    page = int(filters.get("page", 1))
    limit = int(filters.get("limit", 20))
    type_filter = filters.get("type")
    is_read = filters.get("is_read")
    priority = filters.get("priority")

    query = db.query(Notification).filter(Notification.user_id == user_id)

    if type_filter:
        query = query.filter(Notification.type == type_filter)
    if is_read is not None:
        query = query.filter(Notification.is_read == bool(is_read))
    if priority:
        query = query.filter(Notification.priority == priority)

    total = query.count()
    items = (
        query.order_by(Notification.created_at.desc())
        .offset((page - 1) * limit)
        .limit(limit)
        .all()
    )

    unread_count = (
        db.query(func.count(Notification.id))
        .filter(Notification.user_id == user_id, Notification.is_read == False)
        .scalar()
    )

    pagination = {
        "page": page,
        "limit": limit,
        "total": total,
        "total_pages": (total + limit - 1) // limit if limit else 1,
    }
    return items, pagination, unread_count


def mark_as_read(db: Session, user_id: str, notification_id: str) -> bool:
    notification = (
        db.query(Notification)
        .filter(Notification.id == notification_id, Notification.user_id == user_id)
        .first()
    )
    if not notification:
        return False
    if not notification.is_read:
        notification.is_read = True
        notification.read_at = func.current_timestamp()
        db.commit()
    return True


def mark_all_as_read(db: Session, user_id: str) -> int:
    updated = (
        db.query(Notification)
        .filter(Notification.user_id == user_id, Notification.is_read == False)
        .update({
            Notification.is_read: True,
            Notification.read_at: func.current_timestamp(),
        }, synchronize_session=False)
    )
    db.commit()
    return int(updated or 0)


def bulk_mark_read(db: Session, user_id: str, notification_ids: List[str]) -> int:
    updated = (
        db.query(Notification)
        .filter(
            Notification.user_id == user_id,
            Notification.id.in_(notification_ids),
            Notification.is_read == False,
        )
        .update({
            Notification.is_read: True,
            Notification.read_at: func.current_timestamp(),
        }, synchronize_session=False)
    )
    db.commit()
    return int(updated or 0)


def delete_notification(db: Session, user_id: str, notification_id: str) -> bool:
    deleted = (
        db.query(Notification)
        .filter(Notification.id == notification_id, Notification.user_id == user_id)
        .delete(synchronize_session=False)
    )
    db.commit()
    return deleted > 0


def bulk_delete_notifications(db: Session, user_id: str, notification_ids: List[str]) -> int:
    deleted = (
        db.query(Notification)
        .filter(Notification.user_id == user_id, Notification.id.in_(notification_ids))
        .delete(synchronize_session=False)
    )
    db.commit()
    return int(deleted or 0)


def get_or_create_preferences(db: Session, user_id: str) -> NotificationPreferences:
    prefs = (
        db.query(NotificationPreferences)
        .filter(NotificationPreferences.user_id == user_id)
        .first()
    )
    if prefs:
        return prefs
    prefs = NotificationPreferences(user_id=user_id)
    db.add(prefs)
    db.commit()
    db.refresh(prefs)
    return prefs


def update_preferences(db: Session, user_id: str, payload: Dict[str, Any]) -> NotificationPreferences:
    prefs = get_or_create_preferences(db, user_id)

    def set_group(prefix: str, updates: Optional[Dict[str, Any]]):
        if not updates:
            return
        for key, value in updates.items():
            attr = f"{prefix}_{key}"
            if hasattr(prefs, attr) and isinstance(value, bool):
                setattr(prefs, attr, value)

    set_group("email", payload.get("email_notifications"))
    set_group("sms", payload.get("sms_notifications"))
    set_group("push", payload.get("push_notifications"))
    set_group("in_app", payload.get("in_app_notifications"))

    db.commit()
    db.refresh(prefs)
    return prefs


def compute_stats(db: Session, user_id: str) -> Dict[str, Any]:
    total = db.query(func.count(Notification.id)).filter(Notification.user_id == user_id).scalar() or 0
    unread = db.query(func.count(Notification.id)).filter(Notification.user_id == user_id, Notification.is_read == False).scalar() or 0
    read = total - unread

    by_type_rows = (
        db.query(Notification.type, func.count(Notification.id))
        .filter(Notification.user_id == user_id)
        .group_by(Notification.type)
        .all()
    )
    by_type = {t: int(c) for t, c in by_type_rows}

    by_priority_rows = (
        db.query(Notification.priority, func.count(Notification.id))
        .filter(Notification.user_id == user_id)
        .group_by(Notification.priority)
        .all()
    )
    by_priority = {p: int(c) for p, c in by_priority_rows}

    # Approximate recent activity
    today = db.query(func.count(Notification.id)).filter(
        Notification.user_id == user_id,
        func.date(Notification.created_at) == func.current_date()
    ).scalar() or 0

    this_week = db.query(func.count(Notification.id)).filter(
        Notification.user_id == user_id,
        Notification.created_at >= func.date_trunc('week', func.current_timestamp())
    ).scalar() or 0

    this_month = db.query(func.count(Notification.id)).filter(
        Notification.user_id == user_id,
        Notification.created_at >= func.date_trunc('month', func.current_timestamp())
    ).scalar() or 0

    return {
        "total_notifications": int(total),
        "unread_count": int(unread),
        "read_count": int(read),
        "by_type": by_type,
        "by_priority": by_priority,
        "recent_activity": {
            "today": int(today),
            "this_week": int(this_week),
            "this_month": int(this_month),
        },
    }




def register_push_token(db: Session, user_id: str, expo_push_token: str, platform: Optional[str] = None) -> None:
    """Upsert a device's Expo push token; re-activate if seen before."""
    from core.model import PushDeviceToken

    token = (expo_push_token or "").strip()
    if not token.startswith("ExponentPushToken["):
        raise ValueError("Invalid Expo push token")
    row = db.query(PushDeviceToken).filter(PushDeviceToken.expo_push_token == token).first()
    if row:
        row.user_id = user_id
        row.platform = platform or row.platform
        row.is_active = True
    else:
        row = PushDeviceToken(user_id=user_id, expo_push_token=token, platform=platform, is_active=True)
        db.add(row)
    db.commit()


def remove_push_token(db: Session, user_id: str, expo_push_token: str) -> None:
    """Deactivate a token on logout (keeps the row for diagnostics)."""
    from core.model import PushDeviceToken

    db.query(PushDeviceToken).filter(
        PushDeviceToken.user_id == user_id,
        PushDeviceToken.expo_push_token == (expo_push_token or "").strip(),
    ).update({"is_active": False}, synchronize_session=False)
    db.commit()
